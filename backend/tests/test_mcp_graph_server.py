"""Phase 6 checkpoint 4b: the graph MCP server.

The load-bearing test here is the UTF-8 one, and it is a HARD acceptance
criterion rather than a nicety (contract §17.35, pinned in decisions.md before
this was built). The server returns FILE PATHS and RAW IMPORT SPECIFIERS from
arbitrary repositories; on Windows a spawned process defaults its streams to
cp1252, and without an explicit reconfigure every non-ASCII path is corrupted.

Three things about that test are deliberate and easy to get wrong:

  * It sends RAW UTF-8 (`ensure_ascii=False`). With json's default the payload
    is escaped to \\uXXXX before it reaches the stream, the bytes on the wire are
    pure ASCII, ASCII survives cp1252 untouched, and NEITHER arm can fail. A
    first version of this canary did exactly that and proved nothing.
  * It compares by CODEPOINT, never by glyph, because the terminal rendering the
    comparison is cp1252 too and will misreport what it received.
  * The negative-control canary (`test_LOADBEARING_the_canary_fails_without_
    the_reconfigure`) FORCES the corrupting condition (stdin decoded as
    cp1252) rather than deleting the fix and hoping the platform default is
    bad. A first version deleted the call instead, which is Windows-specific:
    on a Linux box with a UTF-8 locale, stdin/stdout are UTF-8 by default even
    undisturbed, so deleting the call proves nothing there. §17.35, instance 4.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CodeFile, CodeFileRank, CodeImport, Repo

BACKEND = Path(__file__).resolve().parents[1]
SERVER = BACKEND / "mcp_graph_server.py"

# U+00E9 accented Latin, U+2014 em dash, U+4E2D U+6587 CJK, U+1F600 emoji --
# the emoji is past the BMP, which catches anything assuming 16-bit code units.
NON_ASCII_PATH = "src/café—中文\U0001f600/target.py"
NON_ASCII_SPEC = "pkg.naïve—中文"


def _seed(db_path):
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    repo = Repo(host="local", owner="acme", name="utf8", local_path="/x",
                source_kind="local", last_ingested_sha="deadbeef")
    db.add(repo); db.flush()
    tgt = CodeFile(repo_id=repo.id, path=NON_ASCII_PATH, language="python",
                   content_sha256="a", size_bytes=1, line_count=1, fan_in=1)
    src = CodeFile(repo_id=repo.id, path="src/plain.py", language="python",
                   content_sha256="b", size_bytes=1, line_count=1)
    db.add_all([tgt, src]); db.flush()
    db.add(CodeFileRank(repo_id=repo.id, file_id=tgt.id, scorer="legacy",
                        score=1.0, rank=1))
    db.add(CodeImport(repo_id=repo.id, from_file_id=src.id, to_file_id=tgt.id,
                      raw_specifier="x", resolved=True, line_number=1, kind="static"))
    db.add(CodeImport(repo_id=repo.id, from_file_id=tgt.id, to_file_id=None,
                      raw_specifier=NON_ASCII_SPEC, resolved=False,
                      line_number=2, kind="static"))
    db.commit()
    rid = repo.id
    db.close()
    return rid


def _ask(server, db_path, args, cwd=None):
    """Drive the server over stdio as a real MCP client does -- RAW UTF-8."""
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db_path}")
    p = subprocess.Popen([sys.executable, str(server)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         encoding="utf-8", bufsize=1,
                         cwd=str(cwd or BACKEND), env=env)
    try:
        def rpc(o, reply=True):
            p.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline()) if reply else None

        rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"}}})
        rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, reply=False)
        r = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "neighborhood", "arguments": args}})
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    res = r["result"]
    txt = res["content"][0]["text"]
    try:
        return res["isError"], json.loads(txt)
    except json.JSONDecodeError:
        return res["isError"], txt


@pytest.fixture
def seeded(tmp_path):
    db_path = str(tmp_path / "utf8.db").replace("\\", "/")
    return db_path, _seed(db_path)


class TestUtf8Canary:
    """HARD ACCEPTANCE CRITERION for checkpoint 4b."""

    def test_LOADBEARING_non_ascii_paths_survive_the_wire_exactly(self, seeded):
        db_path, rid = seeded
        is_err, out = _ask(SERVER, db_path, {"repo": str(rid),
                                             "file_path": NON_ASCII_PATH})
        assert is_err is False, f"server returned an error: {out}"
        assert isinstance(out, dict)
        # By codepoint. Comparing rendered glyphs would let a cp1252 terminal
        # decide whether this test passes.
        assert [ord(c) for c in out["file"]["p"]] == [ord(c) for c in NON_ASCII_PATH], (
            "a non-ASCII file path did not survive the stdio round trip -- "
            "every path in a repo with accented or CJK names would be returned "
            "well-formed and wrong")
        assert out["imports"]["unresolved"][0]["spec"] == NON_ASCII_SPEC

    def test_LOADBEARING_the_canary_fails_without_the_reconfigure(self, seeded, tmp_path):
        """Observe the failure, per §15.1 -- constructed DETERMINISTICALLY, not
        borrowed from a platform default (§17.35, instance 4: the enforcement
        of §17.35 was itself platform-fragile). The original version deleted
        the reconfigure call and trusted the OS to supply a bad default in its
        place -- true on Windows (cp1252), false on Linux under a UTF-8 locale
        (`C.UTF-8` here), where stdin/stdout are UTF-8 even undisturbed.
        Deleting the call on this machine changes nothing, so the old version
        of this canary could not fail here and proved nothing (§15.1) -- a
        canary that relies on a platform default to produce the failure it
        tests for is not portable, and silently stops discriminating on any
        platform whose default happens to be safe.

        The fix: force the CHILD's stdin decoder to cp1252 explicitly, on
        purpose, independent of this machine's actual default. That is a
        property of the FIX under test (does the server's own reconfigure
        call protect it against a bad decoder), not a property of the
        platform running the test. stdout is deliberately left correctly
        UTF-8 (not disabled) so the corrupted reply is still well-formed bytes
        the harness can read -- the failure under test is 'wrong content,
        plausible reply', per §17.35's own description of the original
        incident, not 'the process falls over', and a crash would prove the
        wrong thing.

        The broken copy must live BESIDE the real server: it does
        `sys.path.insert(0, Path(__file__).parent)` to find `app`, so a copy
        elsewhere dies on import and would fail for a reason that has nothing
        to do with encoding.
        """
        db_path, rid = seeded

        # Canary the canary (§17.33): prove the corrupting condition is real
        # BEFORE trusting it, independent of any subprocess or platform. If
        # this payload's UTF-8 bytes happened to round-trip cleanly through a
        # cp1252 decode, forcing cp1252 below would demonstrate nothing.
        corrupted_locally = NON_ASCII_PATH.encode("utf-8").decode("cp1252")
        assert corrupted_locally != NON_ASCII_PATH, (
            "the chosen payload round-trips cleanly through cp1252 -- it "
            "cannot demonstrate the corruption this canary exists to catch")

        src = SERVER.read_text(encoding="utf-8")
        # SURGICAL: replace the reconfigure block and change nothing else. An
        # earlier version sliced from the block to the next landmark and
        # swallowed an unrelated line, so the broken server died on NameError
        # -- failing for a reason that had nothing to do with encoding. A
        # canary that fails for the wrong reason proves nothing.
        block = (
            'for _stream in (sys.stdin, sys.stdout):\n'
            '    try:\n'
            '        _stream.reconfigure(encoding="utf-8")\n'
            '    except Exception:  # pragma: no cover - non-reconfigurable stream\n'
            '        pass'
        )
        assert src.count(block) == 1, "the reconfigure block moved; canary stale"
        # DETERMINISTIC corruption, not a deleted call: stdin is forced to
        # decode as cp1252 (wrong, on every platform) while stdout stays
        # UTF-8 (correct, so the reply is readable and the harness cannot
        # crash for a reason unrelated to what is under test).
        broken_block = (
            'try:\n'
            '    sys.stdin.reconfigure(encoding="cp1252")\n'
            'except Exception:  # pragma: no cover - non-reconfigurable stream\n'
            '    pass\n'
            'try:\n'
            '    sys.stdout.reconfigure(encoding="utf-8")\n'
            'except Exception:  # pragma: no cover - non-reconfigurable stream\n'
            '    pass'
        )
        broken_src = src.replace(block, broken_block)

        broken = BACKEND / "_mcp_utf8_canary_tmp.py"
        broken.write_text(broken_src, encoding="utf-8")
        try:
            is_err, out = _ask(broken, db_path, {"repo": str(rid),
                                                 "file_path": NON_ASCII_PATH})
        finally:
            broken.unlink(missing_ok=True)

        # With stdin forced to decode as cp1252, the path arrives mangled, so
        # it matches no file in the graph. Either it errors on the lookup or
        # it returns a different path -- both are the corruption; neither is
        # a clean answer.
        mangled = is_err is True or (
            isinstance(out, dict) and out["file"]["p"] != NON_ASCII_PATH)
        assert mangled, (
            "the server returned the correct path even with stdin FORCED to "
            "decode as cp1252 -- this canary cannot discriminate and the "
            "gate is meaningless")


class TestServerContract:
    def test_it_exposes_the_neighborhood_tool(self):
        src = SERVER.read_text(encoding="utf-8")
        assert '"name": "neighborhood"' in src

    def test_an_unknown_repo_names_what_exists(self, seeded):
        """A caller that guessed wrong is told the options rather than refused,
        and it comes back as tool content so the model can read and correct
        itself instead of seeing an opaque protocol error."""
        db_path, _ = seeded
        is_err, out = _ask(SERVER, db_path, {"repo": "nope/nope",
                                             "file_path": "x.py"})
        assert is_err is True
        assert "unknown repo" in out and "acme/utf8" in out

    def test_it_imports_no_mcp_sdk(self):
        """Stdlib-only for the protocol: the SDK upgrades starlette over the
        pinned version and breaks fastapi in this venv (§17.34)."""
        src = SERVER.read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith(("#", '"""', "*")))
        assert "import mcp" not in code and "from mcp" not in code


class TestWorkingDirectoryCanary:
    """CANARY, and the one the protocol-level test could not have caught.

    Settings carry RELATIVE paths (`sqlite:///./athena.db` and five config
    files), so they resolve against the cwd the CLIENT chose. The first real
    extension-level call spawned the server from the VSCode workspace root and
    got `no such table: repos` -- because SQLite CREATES a missing database file
    rather than refusing, so the server started cleanly and left a 0-byte
    athena.db behind before failing on the first query.

    The protocol test passed throughout: it spawned with cwd=BACKEND and so
    controlled the exact variable that was broken. A test that fixes the
    variable under test cannot fail (§15.1).
    """

    def test_LOADBEARING_it_works_when_spawned_from_another_directory(
            self, seeded, tmp_path):
        db_path, rid = seeded
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        is_err, out = _ask(SERVER, db_path, {"repo": str(rid),
                                             "file_path": NON_ASCII_PATH},
                           cwd=elsewhere)
        assert is_err is False, (
            f"the server failed when spawned from {elsewhere} -- it depends on "
            f"the client's working directory, which the client chooses: {out}")
        assert isinstance(out, dict) and out["file"]["p"] == NON_ASCII_PATH
        assert not (elsewhere / "athena.db").exists(), (
            "a stray database was created in the spawn directory -- the server "
            "resolved a relative path against the caller's cwd")

    def test_it_chdirs_to_its_own_directory(self):
        src = SERVER.read_text(encoding="utf-8")
        assert "os.chdir(BACKEND_DIR)" in src, (
            "the cwd fix was removed; relative settings paths will resolve "
            "against whatever directory the MCP client happened to use")


class TestGraphCacheCanary:
    """The graph is loaded once per repo and reused. Without this, every query
    re-reads 6,584 nodes and 61,559 edges on superset, and the measured cost of
    a neighbourhood would be dominated by the reload rather than the answer."""

    class _StubGraph:
        # _graph_for logs the node/edge counts, so the stub needs that shape --
        # a bare object() makes the test fail on the log line rather than on
        # the thing it is testing.
        nodes = ()
        edges = ()

    def _server_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_mcp_srv", SERVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_LOADBEARING_a_second_query_for_the_same_repo_does_not_reload(self):
        mod = self._server_module()
        calls = []
        mod._GRAPH_CACHE.clear()
        mod.read_repo_graph = lambda db, rid, **kw: (
            calls.append(rid), self._StubGraph())[1]

        mod._graph_for(None, 6)
        mod._graph_for(None, 6)
        assert calls == [6], (
            f"the graph was read {len(calls)} times for one repo -- the cache "
            "is not holding and every query pays the full graph load")

    def test_the_cache_is_per_repo(self):
        mod = self._server_module()
        calls = []
        mod._GRAPH_CACHE.clear()
        mod.read_repo_graph = lambda db, rid, **kw: (
            calls.append(rid), self._StubGraph())[1]

        mod._graph_for(None, 6)
        mod._graph_for(None, 3)
        mod._graph_for(None, 6)
        assert calls == [6, 3], "a different repo must load its own graph"
