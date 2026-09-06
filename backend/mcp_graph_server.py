"""Phase 6 checkpoint 4b: the graph MCP server.

Exposes the file-neighbourhood query to Claude Code over stdio, so an agent
about to change a file can ask the graph what is connected to it instead of
reading the repo to find out.

**STDLIB-ONLY for the protocol.** No `mcp` SDK: installing it upgrades starlette
over the pinned version and breaks fastapi in this venv (contract §17.34). MCP
over stdio is JSON-RPC 2.0 in newline-delimited JSON, and checkpoint 4a proved a
hand-rolled handshake works. The only imports beyond the standard library are
this project's OWN code, which is already installed.

**It must run under `backend/venv`'s interpreter**, because it imports the app's
services. That is USING the venv, not installing into it — nothing here adds a
dependency.

**Boundary discipline, unchanged from the rest of Phase 6.** This reads through
`graph_read.read_repo_graph` and calls `neighborhood.read_neighborhood`. It does
not touch tables, and it does not touch atlas code.

**The graph is loaded ONCE PER REPO and cached for the process lifetime.** A
neighbourhood query otherwise re-reads the whole graph per call — on superset
that is 6,584 nodes and 61,559 edges of work to answer a question about one
file, and the measured per-query cost would be dominated by the reload rather
than by the neighbourhood. Caching is also what "the graph as standing context"
actually means: load it once, then answer cheaply and repeatedly.

The cache's honesty property: `read_neighborhood` stamps every answer with the
`last_ingested_sha` OF THE GRAPH IT WAS GIVEN, so a cached answer reports the
snapshot it actually came from rather than the current database. A re-ingest
during a server session does not silently change the answers; it makes the
stamp visibly older than `git rev-parse HEAD`, which is the signal the consumer
is meant to check.
"""
import json
import os
import sys
from pathlib import Path

# UTF-8 BEFORE ANY OTHER I/O. This is a hard acceptance criterion for this
# checkpoint, not a nicety (§17.35). MCP mandates UTF-8, but a process spawned
# on Windows defaults stdin/stdout to the ANSI codepage (cp1252 here), and the
# failure is SILENT: a path containing any multi-byte character round-trips
# "successfully" and comes back well-formed and corrupt. This server returns
# FILE PATHS and RAW IMPORT SPECIFIERS from arbitrary repositories, so that is
# not a cosmetic concern — it is the same class of failure as returning an
# incomplete answer, and it is canaried in tests/test_mcp_graph_server.py.
for _stream in (sys.stdin, sys.stdout):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - non-reconfigurable stream
        pass

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# WORKING DIRECTORY, before the app is imported. Settings carry RELATIVE paths --
# `sqlite:///./athena.db`, `./config/ranking_weights.yaml` and four more -- which
# resolve against the CURRENT WORKING DIRECTORY. An MCP client spawns this server
# from wherever it likes (the VSCode extension used the workspace root, one level
# above the repo), and then every one of those paths points somewhere else.
#
# The database case fails in the worst possible way: SQLite CREATES a missing
# file rather than refusing, so the server starts cleanly, reports no error, and
# only falls over on the first query with `no such table: repos` -- having left a
# 0-byte athena.db behind. The protocol-level test could not catch this because
# it spawned the server with cwd=backend and so controlled the one variable that
# was wrong; only the real client, launching from its own directory, exposed it.
#
# chdir fixes the whole class rather than just the database.
os.chdir(BACKEND_DIR)

from app.db.database import SessionLocal  # noqa: E402
from app.services.codebase.graph_read import read_repo_graph  # noqa: E402
from app.services.codebase.neighborhood import (  # noqa: E402
    DEFAULT_BUDGET_TOKENS, read_neighborhood,
)

SERVER_NAME = "athena-graph"
SERVER_VERSION = "1.0.0"
FALLBACK_PROTOCOL = "2025-06-18"

# repo_id -> RepoGraphT, for the process lifetime. See the module docstring for
# why this is cached rather than read per call.
_GRAPH_CACHE = {}

TOOLS = [
    {
        "name": "neighborhood",
        "description": (
            "Given a file in an ingested repository, return its dependency "
            "neighbourhood: what it imports (including imports that did not "
            "resolve to a file), what imports it (the blast radius of changing "
            "it), its rank and subsystem, and whether its dependencies stay "
            "inside its subsystem or cross into others. Use this BEFORE "
            "reading files to decide which files are worth reading. The result "
            "states the commit it was computed from, and states its own "
            "completeness: no path is ever dropped to fit the budget."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": (
                        "Repository, as an id (\"6\") or as owner/name "
                        "(\"apache/superset\"). Call with an unknown value to "
                        "get the list of ingested repositories."
                    ),
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Repo-relative path, e.g. \"superset/models/core.py\"."
                    ),
                },
                "budget": {
                    "type": "integer",
                    "description": (
                        f"Optional token budget, default {DEFAULT_BUDGET_TOKENS}. "
                        "The result sheds its second hop and then per-neighbour "
                        "metadata to fit, but NEVER drops a path; if it still "
                        "cannot fit it says so and reports the shortfall."
                    ),
                },
                "second_hop": {
                    "type": "boolean",
                    "description": "Include a bounded one-more-hop frontier. Off by default.",
                },
            },
            "required": ["repo", "file_path"],
            "additionalProperties": False,
        },
    },
]


def log(msg):
    # stdout carries JSON-RPC only; anything else on it corrupts the stream.
    print(f"[athena-graph] {msg}", file=sys.stderr, flush=True)


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _repos(db):
    from sqlalchemy import inspect, text
    if not inspect(db.get_bind()).has_table("repos"):
        # Locatable rather than a raw driver message. If this fires, the server
        # is pointed at the wrong file -- almost certainly a cwd or DATABASE_URL
        # problem, and almost certainly at an empty database SQLite created for
        # us without complaint.
        raise ValueError(
            f"no 'repos' table at {db.get_bind().url!r} (resolved from cwd "
            f"{os.getcwd()!r}). The server is pointed at the wrong database; "
            f"SQLite creates a missing file silently rather than failing, so an "
            f"empty database looks like a working one.")
    return db.execute(text(
        "SELECT id, host, owner, name FROM repos ORDER BY id")).all()


def _resolve_repo(db, token: str) -> int:
    """Accept an id or an owner/name. Unknown values raise with the LIST, so a
    caller that guessed wrong is told what exists rather than just refused."""
    rows = _repos(db)
    t = (token or "").strip().lower()
    for rid, host, owner, name in rows:
        if t == str(rid):
            return rid
        for form in (f"{owner}/{name}", f"{host}/{owner}/{name}", name):
            if t == (form or "").lower():
                return rid
    available = ", ".join(f"{r[0]}={r[2]}/{r[3]}" for r in rows)
    raise ValueError(f"unknown repo {token!r}. Ingested repositories: {available}")


def _graph_for(db, repo_id: int):
    if repo_id not in _GRAPH_CACHE:
        log(f"loading graph for repo {repo_id} (first query this session)")
        _GRAPH_CACHE[repo_id] = read_repo_graph(db, repo_id, include_symbols=False)
        g = _GRAPH_CACHE[repo_id]
        log(f"cached repo {repo_id}: {len(g.nodes):,} nodes, {len(g.edges):,} edges")
    return _GRAPH_CACHE[repo_id]


def _tool_neighborhood(args: dict) -> dict:
    db = SessionLocal()
    try:
        repo_id = _resolve_repo(db, args.get("repo", ""))
        graph = _graph_for(db, repo_id)
        return read_neighborhood(
            db, repo_id, args["file_path"],
            second_hop=bool(args.get("second_hop", False)),
            budget_tokens=int(args.get("budget") or DEFAULT_BUDGET_TOKENS),
            graph=graph,
        )
    finally:
        db.close()


def handle(msg):
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion") or FALLBACK_PROTOCOL
        log(f"initialize, protocolVersion={ver}")
        send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }})
    elif method in ("notifications/initialized", "initialized"):
        log("handshake complete")
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        log(f"tools/call {name!r} {args!r}")
        if name != "neighborhood":
            send({"jsonrpc": "2.0", "id": req_id,
                  "error": {"code": -32602, "message": f"unknown tool {name!r}"}})
            return
        try:
            payload = _tool_neighborhood(args)
            send({"jsonrpc": "2.0", "id": req_id, "result": {
                # Returned as JSON text rather than prose: the caller is a model
                # that will reason over the structure, and a prose rendering
                # would lose the completeness fields it is meant to check.
                "content": [{"type": "text",
                             "text": json.dumps(payload, separators=(",", ":"))}],
                "isError": False,
            }})
        except ValueError as e:
            # A caller error (unknown repo, unknown file) is returned as tool
            # content rather than a protocol error, so the model can read the
            # message and correct itself instead of seeing an opaque failure.
            send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": str(e)}], "isError": True}})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": req_id, "result": {}})
    elif "id" not in msg:
        log(f"ignoring notification {method!r}")
    else:
        send({"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32601, "message": f"method not found: {method!r}"}})


def main():
    log(f"{SERVER_NAME} {SERVER_VERSION} on stdio; "
        f"stdin={sys.stdin.encoding} stdout={sys.stdout.encoding}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"non-JSON line ignored: {e}")
            continue
        try:
            handle(msg)
        except Exception as e:
            log(f"handler error: {e!r}")
            if "id" in msg:
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32603, "message": f"internal error: {e!r}"}})
    log("stdin closed; exiting")


if __name__ == "__main__":
    main()
