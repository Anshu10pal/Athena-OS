#!/usr/bin/env python3
"""Phase 6 checkpoint 5: the PreToolUse enforcement hook.

Makes the graph get consulted BEFORE a source read rather than only when
someone remembers to ask. On the first raw source read of a session, this
hook DENIES the read and redirects to `mcp__athena-graph__neighborhood`.
After firing once it is inert for the rest of that session.

**STRICT by default, and deliberately so.** A nudge would make the model's
compliance a variable in the result, so any measured saving would be
indistinguishable from "how often did the model take a suggestion". Strict
makes the mechanism the thing under test (see decisions.md, checkpoint 5).

**FAIL OPEN, ALWAYS.** Every failure path in this file allows the read. A
hook that blocks because it crashed, or because the database moved, or
because git is missing, would break the session it is supposed to help. The
only path that denies is the one where every precondition is affirmatively
satisfied. `_allow()` is the default return of every branch.

**FIVE PRECONDITIONS, enforced here rather than asserted:**

1. The graph has an answer. Not merely "the file is in an ingested repo" --
   the file's repo-relative path must be PRESENT IN `code_files` for that
   repo. This is the sharpened version, and it is load-bearing: repo 1's
   ingest is currently 7 commits behind HEAD, so `neighborhood.py` and
   `mcp_graph_server.py` exist on disk and are absent from the graph.
   Redirecting a read to a neighbourhood that does not exist is worse than
   not firing. A commits-behind ceiling is a secondary guard on top.
2. First raw source read of the session only, keyed on the `session_id`
   the hook receives on stdin -- not a file this hook could itself block.
3. Source files only, from the atlas's OWN extension table, parsed out of
   `languages.py` rather than restated here (§17.33: encode the constraint
   where it cannot drift). `--selftest` compares the parse against the
   authoritative import.
4. An explicit, DISCOVERABLE override -- the deny message names it.
5. A kill switch that needs no file read: an env var, or a sentinel file
   creatable from Bash, which this hook never blocks.
"""
import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# Resolved from THIS FILE, never from the cwd. The MCP server's cwd bug
# (§ checkpoint 4b) was exactly this: a relative path resolved against
# whatever directory the client happened to spawn from.
SCRIPT = Path(__file__).resolve()
BACKEND_DIR = SCRIPT.parent.parent
REPO_ROOT = BACKEND_DIR.parent
DB_PATH = BACKEND_DIR / "athena.db"
LANGUAGES_PY = BACKEND_DIR / "app" / "services" / "codebase" / "languages.py"

STATE_DIR = Path(os.environ.get(
    "ATHENA_HOOK_STATE_DIR", Path.home() / ".cache" / "athena-read-hook"))
DISABLE_SENTINEL = STATE_DIR / "DISABLED"
BYPASS_SENTINEL = STATE_DIR / "BYPASS_ONCE"

# Deliberately generous. The real protection is precondition 1's exact
# per-file presence check, plus the fact that every neighbourhood answer is
# stamped with the SHA it was computed from -- so a stale answer is
# DETECTABLE by its consumer rather than silently wrong. This ceiling only
# catches the case where the ingest is so old the answer would mislead.
DEFAULT_MAX_COMMITS_BEHIND = 100

TOOL_NAME = "mcp__athena-graph__neighborhood"


def _allow():
    """The default. Emitting nothing lets the tool call proceed."""
    print(json.dumps({}))
    sys.exit(0)


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _git(args, cwd, timeout=5):
    """Git, with a timeout. Returns None rather than raising."""
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           encoding="utf-8")
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def source_extensions():
    """The atlas's OWN extension table, parsed (not imported -- languages.py
    pulls in tree-sitter, far too heavy to pay before every Read) and not
    restated (a second copy would drift silently the moment Phase 7 adds a
    language). Returns None if the literal cannot be found, which fails open."""
    try:
        src = LANGUAGES_PY.read_text(encoding="utf-8")
        m = re.search(r"EXTENSION_LANGUAGE\s*=\s*(\{.*?\})", src, re.S)
        if not m:
            return None
        table = ast.literal_eval(m.group(1))
        return {k.lower() for k in table} or None
    except Exception:
        return None


def repo_identity(remote_url):
    """github.com/Anshu10pal/Athena-OS from either URL form. The identity is
    machine-independent, which `repos.local_path` is NOT -- every local_path
    in this database is still a Windows path from the previous machine."""
    if not remote_url:
        return None
    m = re.match(r"^(?:https?://|git@)([^/:]+)[/:]([^/]+)/(.+?)(?:\.git)?$",
                 remote_url.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2), m.group(3)


def main():
    # ---- stdin: anything unreadable fails open -------------------------
    try:
        payload = json.load(sys.stdin)
    except Exception:
        _allow()

    # ---- precondition 5: the kill switch, checked FIRST ----------------
    # Before anything that could itself fail. An env var for a persistent
    # global off, and a sentinel file so it can also be thrown mid-session
    # from Bash -- which this hook never blocks. Shell state does not carry
    # between Bash calls, so the sentinel is the one that works right now.
    if os.environ.get("ATHENA_HOOK_DISABLE") == "1":
        _allow()
    try:
        if DISABLE_SENTINEL.exists():
            _allow()
    except Exception:
        _allow()

    if payload.get("tool_name") != "Read":
        _allow()

    file_path = (payload.get("tool_input") or {}).get("file_path")
    session_id = payload.get("session_id")
    if not file_path or not session_id:
        _allow()

    try:
        target = Path(file_path).resolve()
    except Exception:
        _allow()

    # ---- precondition 3: source files only -----------------------------
    exts = source_extensions()
    if not exts or target.suffix.lower() not in exts:
        _allow()

    # ---- precondition 2: first source read of this session only --------
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        marker = STATE_DIR / f"session-{re.sub(r'[^A-Za-z0-9_.-]', '_', session_id)}.fired"
        if marker.exists():
            _allow()
    except Exception:
        _allow()

    # ---- precondition 4: the explicit override -------------------------
    # One-shot: the sentinel is consumed, so a bypass covers a single call
    # rather than silently disabling strict mode for the rest of the session.
    if os.environ.get("ATHENA_HOOK_BYPASS") == "1":
        _allow()
    try:
        if BYPASS_SENTINEL.exists():
            BYPASS_SENTINEL.unlink(missing_ok=True)
            _allow()
    except Exception:
        _allow()

    # ---- precondition 1: the graph must actually have an answer --------
    if not DB_PATH.exists():
        _allow()

    toplevel = _git(["rev-parse", "--show-toplevel"], target.parent)
    if not toplevel:
        _allow()                       # not in a git repo at all
    ident = repo_identity(_git(["remote", "get-url", "origin"], toplevel))
    if not ident:
        _allow()
    host, owner, name = ident

    try:
        rel = target.relative_to(Path(toplevel).resolve()).as_posix()
    except Exception:
        _allow()

    try:
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
        row = db.execute(
            "SELECT id, last_ingested_sha FROM repos "
            "WHERE lower(host)=? AND lower(owner)=? AND lower(name)=?",
            (host, owner.lower(), name.lower())).fetchone()
        if not row:
            _allow()                   # repo is not in the atlas
        repo_id, ingested_sha = row

        # THE sharpened check: this exact path must be in the graph. A file
        # added after the last ingest is on disk and absent here, and
        # redirecting to a neighbourhood that does not exist is pure cost.
        known = db.execute(
            "SELECT 1 FROM code_files WHERE repo_id=? AND path=?",
            (repo_id, rel)).fetchone()
        db.close()
        if not known:
            _allow()
    except Exception:
        _allow()

    # ---- precondition 1c: staleness ceiling ----------------------------
    behind = None
    if ingested_sha:
        out = _git(["rev-list", "--count", f"{ingested_sha}..HEAD"], toplevel)
        if out is None:
            _allow()                   # ingested commit not in this history
        try:
            behind = int(out)
        except Exception:
            _allow()
        try:
            ceiling = int(os.environ.get("ATHENA_HOOK_MAX_COMMITS_BEHIND",
                                         DEFAULT_MAX_COMMITS_BEHIND))
        except Exception:
            ceiling = DEFAULT_MAX_COMMITS_BEHIND
        if behind > ceiling:
            _allow()

    # ---- every precondition satisfied: fire, once ----------------------
    try:
        marker.write_text(f"{file_path}\n", encoding="utf-8")
    except Exception:
        _allow()      # if the session cannot be marked, it would fire again

    stale = ""
    if behind:
        stale = (f"\n\nNOTE: this repo's graph was ingested {behind} commit(s) "
                 f"before HEAD ({ingested_sha[:12]}). The answer states the SHA "
                 f"it came from, so check that stamp before trusting it on "
                 f"recently-changed files.")

    _deny(
        f"ATHENA GRAPH (checkpoint 5, strict mode): query the graph before "
        f"reading source.\n\n"
        f"This is the first raw source read of the session. Call "
        f"`{TOOL_NAME}` first:\n"
        f'    repo="{owner}/{name}", file_path="{rel}"\n\n'
        f"It returns what this file imports, what imports it (its blast "
        f"radius), its rank and subsystem -- so you can decide which files "
        f"are actually worth reading instead of exploring to find out. Then "
        f"read what the graph pointed you at; this hook is now inert for the "
        f"rest of the session and will not block again.{stale}\n\n"
        f"To bypass for this one call:  touch {BYPASS_SENTINEL}\n"
        f"To disable the hook entirely: touch {DISABLE_SENTINEL}\n"
        f"                              (or set ATHENA_HOOK_DISABLE=1)"
    )


def selftest():
    """Guard against the parsed extension table drifting from the real one.
    Imports the authoritative module (paying the tree-sitter cost, which is
    fine outside the hot path) and compares."""
    sys.path.insert(0, str(BACKEND_DIR))
    from app.services.codebase.languages import EXTENSION_LANGUAGE
    parsed, real = source_extensions(), {k.lower() for k in EXTENSION_LANGUAGE}
    ok = parsed == real
    print(f"parsed={sorted(parsed or [])}\nimported={sorted(real)}\n"
          f"{'MATCH' if ok else 'DRIFT -- the hook and the atlas disagree'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        main()
    except Exception:
        _allow()       # the outermost fail-open; nothing here may block a read
