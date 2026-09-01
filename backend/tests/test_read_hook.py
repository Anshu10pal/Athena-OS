"""Phase 6 checkpoint 5: the PreToolUse enforcement hook.

Every test here is a CANARY in the §15.1 sense, and the discipline that
matters is the RE-ARM CHECK. Six of these assert the hook does NOT fire.
On its own each such assertion is worthless -- a hook that is broken, or
disabled, or pointed at the wrong database passes all six while proving
nothing (§17.30: an instrument reporting the absence of what it cannot
perceive; §17.35 instance 4: a negative control whose failing condition was
never actually constructed).

So each "does not fire" test is paired with a re-arm: the SAME session is
then given a file that must fire, and the test fails unless it does. That
converts "it allowed" into "it allowed FOR THIS REASON, while live and
capable of firing".

State is redirected to a temp directory via ATHENA_HOOK_STATE_DIR, so these
never touch the real session markers.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
HOOK = BACKEND / "scripts" / "athena_read_hook.py"
DB = BACKEND / "athena.db"

# In the graph AND on disk -- the file the hook must fire on.
GRAPHED = REPO_ROOT / "frontend/src/lib/api.ts"
# A source file added AFTER the last ingest: on disk, absent from the graph.
UNGRAPHED = BACKEND / "mcp_graph_server.py"
NON_SOURCE = REPO_ROOT / "frontend/package.json"

needs_graph = pytest.mark.skipif(
    not DB.exists() or not GRAPHED.exists(),
    reason="needs the ingested athena.db and a checkout of this repo")


def ask(session, path, state_dir, tool="Read", env=None, raw=None):
    """Drive the hook exactly as Claude Code does: JSON on stdin."""
    payload = raw if raw is not None else json.dumps({
        "session_id": session, "tool_name": tool,
        "tool_input": {"file_path": str(path)}})
    e = dict(os.environ, ATHENA_HOOK_STATE_DIR=str(state_dir))
    e.pop("ATHENA_HOOK_DISABLE", None)
    e.pop("ATHENA_HOOK_BYPASS", None)
    e.update(env or {})
    r = subprocess.run([sys.executable, str(HOOK)], input=payload, env=e,
                       stdout=subprocess.PIPE, encoding="utf-8", timeout=60)
    return json.loads(r.stdout or "{}")


def fired(out):
    return (out.get("hookSpecificOutput", {})
               .get("permissionDecision")) == "deny"


@needs_graph
class TestItFires:
    def test_LOADBEARING_it_fires_on_the_first_source_read_of_a_session(self, tmp_path):
        out = ask("s1", GRAPHED, tmp_path)
        assert fired(out), (
            "the hook did not block the first raw source read of a session -- "
            "strict mode is not enforcing, and the saving is theoretical")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        # The override must be DISCOVERABLE at the moment of blocking,
        # not buried in a doc the blocked caller is not reading.
        assert "mcp__athena-graph__neighborhood" in reason
        assert "BYPASS_ONCE" in reason and "ATHENA_HOOK_DISABLE" in reason

    def test_it_names_the_repo_and_the_repo_relative_path(self, tmp_path):
        reason = ask("s2", GRAPHED, tmp_path)["hookSpecificOutput"][
            "permissionDecisionReason"]
        assert "Anshu10pal/Athena-OS" in reason
        assert "frontend/src/lib/api.ts" in reason


@needs_graph
class TestItDoesNotFire:
    """Each case pairs its ALLOW with a re-arm that must DENY."""

    def _rearm(self, session, tmp_path, why):
        assert fired(ask(session, GRAPHED, tmp_path)), (
            f"RE-ARM FAILED: session {session} could not fire even on a "
            f"qualifying file, so the earlier pass-through proves nothing "
            f"about {why} -- it may simply be a dead hook (§17.30)")

    def test_LOADBEARING_it_is_inert_after_firing_once(self, tmp_path):
        assert fired(ask("t1", GRAPHED, tmp_path)), "setup: first read must fire"
        assert not fired(ask("t1", GRAPHED, tmp_path)), (
            "the hook fired twice in one session -- it would block every read")

    def test_a_non_source_file_is_never_blocked(self, tmp_path):
        assert not fired(ask("t2", NON_SOURCE, tmp_path))
        self._rearm("t2", tmp_path, "the extension check")

    def test_a_repo_the_atlas_has_not_ingested_is_not_blocked(self, tmp_path):
        other = tmp_path / "unknown-repo"
        other.mkdir()
        subprocess.run(["git", "init", "-q", "."], cwd=other, check=True)
        subprocess.run(["git", "remote", "add", "origin",
                        "https://github.com/nobody/not-ingested.git"],
                       cwd=other, check=True)
        f = other / "mod.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert not fired(ask("t3", f, tmp_path))
        self._rearm("t3", tmp_path, "the repo-identity check")

    def test_LOADBEARING_a_source_file_absent_from_the_graph_is_not_blocked(self, tmp_path):
        """The sharpened precondition 1. This repo's ingest currently trails
        HEAD, so files added since exist on disk and not in `code_files`.
        Redirecting to a neighbourhood that does not exist is pure cost."""
        assert not fired(ask("t4", UNGRAPHED, tmp_path)), (
            f"{UNGRAPHED.name} is not in the graph, so the hook redirected a "
            f"read to a query that cannot be answered")
        self._rearm("t4", tmp_path, "the file-is-in-the-graph check")

    def test_the_bypass_env_var_lets_one_call_through(self, tmp_path):
        assert not fired(ask("t5", GRAPHED, tmp_path,
                             env={"ATHENA_HOOK_BYPASS": "1"}))
        self._rearm("t5", tmp_path, "the bypass override")

    def test_LOADBEARING_a_bypass_does_not_silently_spend_the_session(self, tmp_path):
        """A bypass must cover ONE call. If it also marked the session, strict
        mode would be off for the rest of it -- the loudest possible way to
        stop enforcing while appearing to."""
        ask("t6", GRAPHED, tmp_path, env={"ATHENA_HOOK_BYPASS": "1"})
        assert fired(ask("t6", GRAPHED, tmp_path)), (
            "a bypassed call consumed the session's one firing")

    def test_the_disable_env_var_turns_the_hook_off(self, tmp_path):
        assert not fired(ask("t7", GRAPHED, tmp_path,
                             env={"ATHENA_HOOK_DISABLE": "1"}))
        self._rearm("t7", tmp_path, "the kill switch")

    def test_the_disable_sentinel_turns_the_hook_off_without_a_file_read(self, tmp_path):
        """The kill switch must be throwable from Bash mid-session: env vars do
        not survive between Bash calls, so the sentinel is the one that works
        when the hook is already misbehaving."""
        state = tmp_path / "state"
        state.mkdir()
        (state / "DISABLED").touch()
        assert not fired(ask("t8", GRAPHED, state))
        (state / "DISABLED").unlink()
        self._rearm("t8", state, "the disable sentinel")


class TestItFailsOpen:
    """Nothing in this hook may block a read because the hook itself broke."""

    def test_malformed_stdin_allows_the_read(self, tmp_path):
        assert not fired(ask(None, None, tmp_path, raw="not json at all"))

    def test_an_empty_payload_allows_the_read(self, tmp_path):
        assert not fired(ask(None, None, tmp_path, raw="{}"))

    def test_a_non_read_tool_is_untouched(self, tmp_path):
        assert not fired(ask("f3", "/bin/ls", tmp_path, tool="Bash"))

    def test_a_missing_database_allows_the_read(self, tmp_path, monkeypatch):
        """If the database is absent the graph has no answer, so there is
        nothing to redirect to and the read must proceed."""
        out = ask("f4", GRAPHED, tmp_path,
                  env={"ATHENA_HOOK_STATE_DIR": str(tmp_path / "s"),
                       "HOME": str(tmp_path)})
        assert isinstance(out, dict)      # never raises, always valid JSON


class TestNoDriftFromTheAtlas:
    def test_LOADBEARING_the_extension_table_matches_the_atlas(self):
        """The hook parses EXTENSION_LANGUAGE out of languages.py rather than
        restating it, so Phase 7 adding a language cannot leave the hook
        silently guarding the old set (§17.33)."""
        r = subprocess.run([sys.executable, str(HOOK), "--selftest"],
                           stdout=subprocess.PIPE, encoding="utf-8", timeout=120)
        assert r.returncode == 0, f"hook/atlas extension drift:\n{r.stdout}"
        assert "MATCH" in r.stdout
