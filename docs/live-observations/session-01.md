# Live observation session 01

**Date:** 2026-09-01
**Task:** Investigate `superset/utils/core.py` database-connection handling — (a) inbound
code paths, (b) the config flag likely involved, (c) blast radius of changing the behaviour.
Investigation only; no fix, no code.

**Setup as found:**
- cwd `/home/hack-t36/Athena` — hook is registered in `athena-os/.claude/settings.json`,
  one level down. Whether it loads from a non-cwd project dir is itself unknown at start.
- `athena.db` has `apache/superset` as repo 6, 6584 files, ingested at `a05a099`.
- **No Superset checkout exists anywhere on the filesystem.** Searched `/` to depth 8.
  So for this task the graph is not "a cheaper alternative to reading files" — it is the
  only source of information that exists. Noted up front because it changes how every
  entry below should be read.
- Session is in Bash-first "auto mode", which routes ordinary file reads to `cat`/`sed`.
  The hook matches the `Read` tool only. Any read done through Bash cannot fire it.

---

## Log

[14:31] [B] file: superset/utils/core.py
what happened: reached for the task's target file, and there is nothing to Read — no Superset checkout exists on disk, so the hook cannot fire on it and never will this session.
was it useful: n/a — the hook's absence here is structural, not a miss.
what I did next: went straight to `neighborhood(apache/superset, superset/utils/core.py)`, which is the only way to see this file at all.

[14:32] [D] file: superset/utils/core.py
what happened: fan_in 346 / fan_out 11, rank 3, `in_cycle: true` — and the single most interesting edge was in `importers`, not `imports`: `superset/config.py` imports utils/core.py and is the ONLY crossing edge in a list of 25 (`crosses: true`, cluster `superset/extensions/storage`).
was it useful: yes — inverted my expected direction of travel; I had assumed core.py would read config, and instead config reads core.py.
what I did next: queried config.py to see the shape of that edge.

[14:33] [D] file: superset/utils/core.py
what happened: the `unresolved` list turned out to be the most diagnostic part of the answer — `sqlite3` (l.31), `ssl` (l.32), `cryptography.hazmat.backends` (l.70), `cryptography.x509` (l.71) sit right next to each other, alongside `sqlalchemy.engine`, `sqlalchemy.dialects.mysql`, `sqlalchemy.engine.reflection`.
was it useful: yes — unresolved stdlib/third-party specs are supposed to be the part you ignore, and here they localised the connection/TLS concern inside a 6000-line utility file better than any first-party edge did.
what I did next: treated ssl + cryptography.x509 as the likely site of the connection-handling code and looked for the config flag that gates it.

[14:35] [D] file: superset/utils/database.py
what happened: fan_in 56, but 52 of the 56 importers are tests/fixtures/examples/cli — its real production fan-in is roughly four files (utils/core.py, extensions/__init__.py, and two examples loaders).
was it useful: yes — a file I would have ranked as a core connection-handling dependency off its fan_in alone is mostly a test convenience surface.
what I did next: demoted it and pushed on `superset/models/core.py` instead.

[14:37] [D] file: superset/models/core.py
what happened: unresolved imports include `sshtunnel` (l.39), `sqlalchemy.pool` (l.61), `sqlalchemy.engine.url` (l.57) and four separate `contextlib` specs (l.29); `superset/databases/ssh_tunnel/models.py` and `superset/commands/database/test_connection.py` appear as importers.
was it useful: yes — this, not utils/core.py, is where engine construction actually lives; utils/core.py holds the helpers it calls.
what I did next: re-centred the answer for (a) on the models/core.py <-> utils/core.py cycle rather than on utils/core.py alone.

[14:39] [E] file: superset/config.py
what happened: config.py has fan_in of only 10 (two of them non-test) despite defining every flag in the product — because Superset reads config through `current_app.config["FLAG"]` at runtime, not through import edges.
was it useful: no — and this is the sharp edge of the session: "which config flag is involved" is a question an import graph structurally cannot answer, no matter how complete the ingest is. Flag consumption leaves no import edge to follow.
what I did next: nothing available in the tool; noted that (b) cannot be answered from the graph and would need a grep over source I do not have. Not the tool being incomplete — the tool being the wrong shape for this one sub-question.

[14:41] [B] file: backend/app/services/codebase/graph_structure.py
what happened: I wanted the hook to fire here and it did not — the `Read` returned 121 lines of file content with no deny, no redirect, nothing.
was it useful: no — this is the session's stop condition tripping. I wanted graph context for this read: the reason I was opening it at all was to find out whether the `cluster` labels in every answer above are trustworthy, and the neighbourhood would have told me its rank and importers first.
what I did next: stopped adding hook observations and diagnosed why, since the value of "it didn't fire" depends entirely on the reason.

[14:43] [C-adjacent] file: backend/scripts/athena_read_hook.py
what happened: fed the hook script a synthetic payload for the exact file I had just Read; it returned a well-formed `permissionDecision: deny` naming `Anshu10pal/Athena-OS`, the correct repo-relative path, and an 8-commits-behind staleness note.
was it useful: yes — decisive. The script's five preconditions all evaluate correctly and it WOULD have blocked that read. The logic is intact; the wiring is not.
what I did next: confirmed no session marker existed in `~/.cache/athena-read-hook/` (only my manual `session-DIAG-manual.fired`) and both kill switches were off — so the harness never invoked the hook at all, rather than invoking it and failing open.

[14:47] [E] file: superset/config.py -> the config flag question
what happened: `code_symbols` for config.py holds only 15 entries for a file whose own source reaches line 3323, because module-level constant assignments are not captured as symbols — so the ~400 config flags Superset defines are invisible to both the graph and the tool.
was it useful: no, for question (b) specifically.
what I did next: fell back to raw SQL against `athena.db` — not to reading files, which was never an option here.

[14:50] [D] file: athena.db schema
what happened: the database has `code_symbols` (name, kind, signature, docstring, line_start/end) and `code_imports.imported_names` — neither of which `neighborhood` exposes.
was it useful: yes, and it reframed the session. The single most load-bearing fact I found all day came out of `imported_names`, not out of the tool: `pessimistic_connection_handling` has exactly ONE production importer, `superset/initialization/__init__.py:84`. The tool told me utils/core.py has fan_in 346; the symbol data told me the connection-handling part of it has fan_in 1.
what I did next: used SQL for the rest of the symbol-level work and logged this as the session's main design finding.

[14:53] [D] file: superset/utils/core.py
what happened: `parse_ssl_cert` and `create_ssl_cert_file` also have tiny production fan-in — `superset/databases/schemas.py:61` and `superset/db_engine_specs/trino.py:53` respectively — and `check_sqlalchemy_uri`, which I expected to find in utils/core.py, is not there at all; it lives in `superset/security/analytics_db_safety.py:40` with a production fan-in of two.
was it useful: yes — file-level fan_in of 346 was actively misleading about blast radius for this question. Every actual connection-handling entry point into this file is a single-digit fan-in symbol.
what I did next: rebuilt answer (c) around the three symbol-level call sites instead of the file-level importer list.

[14:56] [D] file: cluster labels, all answers
what happened: `cluster` reads `superset/migrations/versions` on almost every Superset file, including `superset/utils/core.py` and `superset/models/core.py`, while `superset/config.py` sits in `superset/extensions/storage` and `superset/extensions/__init__.py` in `tests/unit_tests/mcp_service`.
was it useful: no — I do not believe these labels, and `crosses: false` inherits that doubt. One giant cluster named after a migrations directory reads like a cluster-naming artifact (largest-member-wins on a directory with hundreds of near-identical files), not a subsystem.
what I did next: dropped `crosses` from my reasoning entirely and used directory structure as the subsystem proxy for (c). Worth noting this was the read the hook would have contextualised had it fired.

*(Timestamps are sequential markers inside a real 14:30–14:57 UTC window, not per-call clock reads.)*

---

## Answers to the task

### (a) What code paths lead into `superset/utils/core.py`'s database-connection handling

The file-level answer is useless: fan_in 346. The symbol-level answer is three narrow paths,
and they do not overlap.

`superset/utils/core.py` holds exactly three connection-related symbols:

| symbol | lines | production callers |
|---|---|---|
| `pessimistic_connection_handling(some_engine: Engine)` | 832–886 | `superset/initialization/__init__.py:84` — **one** |
| `parse_ssl_cert(certificate) -> Certificate` | 1598–1610 | `superset/databases/schemas.py:61` |
| `create_ssl_cert_file(certificate) -> str` | 1613–1634 | `superset/db_engine_specs/trino.py:53` |

**Path 1 — app startup, metadata DB (the likely one).**
`SupersetAppInitializer` imports `pessimistic_connection_handling` at line 84 and applies it
during init; the relevant neighbours in that class are `setup_db` (1600),
`check_and_warn_database_connection` (1311) and `set_db_default_isolation` (1382). This is a
SQLAlchemy engine event listener installed once at boot, on the Superset metadata engine — so
its failures are *occasional and global*, which matches the reported symptom shape.

**Path 2 — analytics DB connection create/update, via the API schema.**
`superset/databases/schemas.py` is the convergence point: it imports `parse_ssl_cert` from
utils/core.py **and** `check_sqlalchemy_uri` from `superset/security/analytics_db_safety.py`.
Anything posting a DB connection payload (`superset/databases/api.py`,
`superset/commands/database/{create,update,test_connection}.py`) passes through here.

**Path 3 — Trino only.** `db_engine_specs/trino.py` materialises the cert to a temp file.

Engine construction itself is **not** in utils/core.py — it is `Database._get_sqla_engine` at
`superset/models/core.py:629`, with an engine cache evicted by `_evict_engine_cache`
(models/core.py:1578) and a documented regression behind it (`#27897`, "a single Engine per
process/URL, not on every `_get_sqla_engine` call"). utils/core.py and models/core.py import
each other (`from superset.models.core import Database` at utils/core.py:118) and sit in a
cycle. **If something is failing occasionally, the engine cache + its eviction listener is a
more likely site than utils/core.py, and utils/core.py is where the maintainer is looking
because that is where the helper lives.**

### (b) What config flag is likely involved

Answered with lower confidence than (a) and (c), and the reason is worth stating: **an import
graph cannot answer this.** Superset reads config through `current_app.config["FLAG"]` at
runtime; `superset/config.py` has a total fan_in of 10, only two non-test. Flag consumption
leaves no edge.

Best supported candidate: **`PREVENT_UNSAFE_DB_CONNECTIONS`**. Direct evidence — the docstring
of `tests/unit_tests/databases/commands/importers/v1/import_test.py::
test_import_database_sqlite_allowed_with_ignore_permissions`: *"System imports (like examples)
use URIs from server config, not user input, so they should bypass the
PREVENT_UNSAFE_DB_CONNECTIONS check."* The check it gates is `check_sqlalchemy_uri`
(`security/analytics_db_safety.py:40`), reachable on Path 2 above. It fits "occasional": it
fires only on connection create/import, and only for blocklisted drivers (sqlite being the
classic case), so it looks intermittent from the outside.

Two competing candidates I could not rule out, both on Path 1:
- **`SQLALCHEMY_ENGINE_OPTIONS`** — pool params (`pool_pre_ping`, `pool_recycle`) interact
  directly with what `pessimistic_connection_handling` installs; setting it can double up or
  conflict with the boot-time listener.
- Per-database **impersonation / per-user caching**, not a global flag —
  `superset/utils/cache_keys.py::add_impersonation_cache_key_if_needed` ("when the DB
  connection is configured for per-user caching"), which changes engine cache keying.

Strongest independent hint at the actual bug, from a docstring rather than the graph:
`superset/mcp_service/auth.py::_resolve_user_with_retry` — *"retrying once on a stale DB
connection... (e.g. SSL dropped by proxy/load balancer after idle periods). On
OperationalError..."_ That is the classic presentation of a `pessimistic_connection_handling`
gap, and it is Path 1, not Path 2. **Confirming (b) needs one grep for
`config["PREVENT_UNSAFE_DB_CONNECTIONS"]` and `SQLALCHEMY_ENGINE_OPTIONS` over source I do
not have.**

### (c) What else would have to change

**Tier 1 — changes with the behaviour, unavoidable (4 files):**
- `superset/utils/core.py` — the three symbols above.
- `superset/models/core.py` — `_get_sqla_engine` (629), `_evict_engine_cache` (1578),
  `set_sqlalchemy_uri` (501), `safe_sqlalchemy_uri` (1089). Cyclic with utils/core.py, so
  these two move together whether you want them to or not.
- `superset/initialization/__init__.py` — the sole caller of
  `pessimistic_connection_handling`; `setup_db`, `set_db_default_isolation`,
  `check_and_warn_database_connection`.
- `superset/databases/schemas.py` — validation convergence point for Path 2.

**Tier 2 — if the flag or the URI check moves (3 files):**
`superset/security/analytics_db_safety.py`, `superset/commands/database/importers/v1/utils.py`
(its only other production importer), `superset/config.py` (declaration + docs).

**Tier 3 — dialect-specific, only if the SSL/cert contract changes:**
`superset/db_engine_specs/trino.py` (direct caller), then `db_engine_specs/base.py` and the
per-dialect specs that build connect args — `postgres`, `mysql`, `bigquery`, `snowflake`,
`databricks`, `presto`, `clickhouse`.

**Tier 4 — SSH tunnelling.** `superset/models/core.py` imports `sshtunnel` (line 39) and
`superset/databases/ssh_tunnel/models.py` is an importer; tunnelled connections wrap the same
engine path and are a standing source of intermittent connection failure.

**Tests that will break (from fan-in, high confidence):**
`tests/integration_tests/utils_tests.py` (imports both SSL helpers directly),
`tests/unit_tests/models/core_test.py` (holds the `#27897` engine-cache regression test),
`tests/unit_tests/utils/test_core.py`, `tests/unit_tests/config_test.py`,
`tests/integration_tests/security/analytics_db_safety_tests.py`,
`tests/unit_tests/utils/test_impersonation_cache_key.py`,
`tests/integration_tests/test_database_password_encoding.py`,
`tests/unit_tests/db_engine_specs/test_trino.py`, and
`tests/integration_tests/base_tests.py` (fan_in 117 — the shared harness).

**Not affected, despite looking like it should be:** `superset/utils/database.py`. fan_in 56,
but 52 of those are tests, fixtures, examples and CLI. It is a test convenience surface, not
part of the connection path.

---

## Hook firings vs. reads

| | count |
|---|---|
| Hook firings, in-session | **0** |
| Hook firings, manual out-of-band confirmation | 1 (denied correctly) |
| `Read` tool calls | **1** |
| Source/config file reads via Bash (`cat`) | 4 (`.mcp.json`, project `settings.json`, `athena_read_hook.py` ~300 lines, user `settings.json`) |
| `neighborhood` MCP calls | 5 (utils/core.py, utils/database.py, models/core.py, config.py, analytics_db_safety.py) |
| Raw SQL fallback queries against `athena.db` | 6 |
| Bypasses / overrides used | **0** — never needed one |
| Superset source files read | **0** — impossible, none on disk |

The shape is not "hook fired once, then five informed reads." It is: **the hook never fired,
and I read almost no source anyway** — 5 graph calls and 6 SQL queries answered a
three-part blast-radius question across a 6,584-file repo I have zero files of. The ratio that
matters is 11 graph queries to 0 Superset reads, and that was forced by the environment rather
than chosen. Two independent things suppressed the hook: Bash-first auto mode routes ordinary
reads to `cat` (which the `Read` matcher cannot see), and the one real `Read` I did make was
not intercepted at all.

---

## Three lines of honest reflection

**What the tool made easier than reading files would have been.** Ranking a 346-importer list
without opening any of it. `superset/utils/database.py` looked like a core dependency by name
and by fan_in, and one call showed 52 of its 56 importers were tests — I dropped it in about
ten seconds, where reading would have cost several files to reach the same conclusion. The
`unresolved` list, which is nominally the throwaway part of the answer, was the best single
signal I got: seeing `sqlite3`, `ssl`, `cryptography.x509` adjacent at lines 31–71 localised
the connection concern inside a 6,000-line file before I knew a single symbol name.

**What the tool made harder or slower than reading files would have been.** Two things.
The `importers` payload for a rank-3 file is a wall — ~300 paths in `additional_paths`, mostly
migrations and tests, and I had to eyeball it, because the tool sorts by rank but cannot filter
by "is this connection-related". And `cluster` is, I think, wrong: nearly every Superset file
labelled `superset/migrations/versions` makes `crosses` unusable, so the one field that
directly addresses "subsystem boundary" in question (c) is the one field I threw away. Reading
a directory listing would have served me better than the cluster labels did.

**One thing that surprised me.** The tool's headline number was the least useful thing it told
me, and it pointed the wrong way. `fan_in: 346` says "enormous blast radius, tread carefully";
the truth is that this file's *connection-handling* has a production fan-in of **one**
(`initialization/__init__.py:84`), plus two single-caller SSL helpers. File-level fan_in
answered a question I wasn't asking. What actually cracked the task was `code_imports.
imported_names` and `code_symbols.docstring` — both already in `athena.db`, neither exposed by
`neighborhood`. I spent five calls on the tool and got orientation; I spent six SQL queries
and got the answer.

---

## Flagged for the record — not acted on

1. **The hook is not wired into this session (regression, blocking).** Script logic verified
   intact by manual invocation. Two candidate causes, not distinguished from inside the
   session: (i) `.claude/settings.json` lives at `athena-os/`, one level below the session cwd
   `/home/hack-t36/Athena`, so project settings may not load at all; (ii) the settings entry
   uses `{"type":"command","command":<python>,"args":[<script>]}` — Claude Code's PreToolUse
   hook schema takes a single `command` string and, as far as I can tell, has no `args` field,
   which would make the script path silently unpassed. Both are wiring, not logic.
2. **Bash-first auto mode is invisible to a `Read` matcher.** Any session that routes reads
   through `cat`/`sed` cannot be measured by this hook. Worth deciding whether that is
   acceptable or whether the matcher needs to cover `Bash`.
3. **`neighborhood` does not expose `imported_names` or `code_symbols`, and that is where the
   answers were.** Symbol-level fan-in inverted the file-level conclusion on the only question
   that mattered. Strongest single design finding of the session.
4. **Cluster labels look broken on Superset.** One near-universal cluster named
   `superset/migrations/versions`; `superset/extensions/__init__.py` labelled
   `tests/unit_tests/mcp_service`. Makes `crosses` untrustworthy on this repo.
5. **Module-level constants are not captured as symbols**, so config-flag questions are
   unanswerable from the graph on any Flask-config-style codebase. May be a real scope
   boundary rather than a bug — worth naming either way.
6. **A repo can be in the graph with no checkout on disk** (Superset here). The hook's
   precondition 1 assumes the file is readable; this case inverts the tool's premise from
   "cheaper than reading" to "the only thing available", and nothing in the design speaks to
   it.

---

## Addendum — flag 1 resolved from outside the session (2026-09-01)

Flag 1 above named two candidate causes and said they could not be separated from
inside the failure. They can be separated from outside it. Three results:

**The premise was wrong, and that matters more than the mechanism.** The earlier
session's "extension-layer confirmation" was **not a harness fire**. Its transcript
(`da076d61…jsonl`) contains exactly **one** `Read` tool_use — `ranking.py`, line 93 —
and its result at line 94 returned the file's contents, `is_error=None`. The
well-formed deny sits at **line 89**, four entries earlier, as a **Bash
`tool_result`**: the script's own stdout from a synthetic invocation with
`ATHENA_HOOK_STATE_DIR` redirected to a scratchpad probe and `session_id` literally
`"probe-cold-check"`. The marker survives on disk as the receipt. **So there is no
"worked once, then stopped" to explain — the hook has never once been invoked by the
harness, and the disconfirming datum was three entries below the confirming one in
the same session.** §17.16 generalised from numbers to decisions: the instrument that
produced the deny was never reported beside it.

**(1) Settings location — CONFIRMED, sufficient alone.** No `.claude/` exists at or
above the session cwd `/home/hack-t36/Athena`; the only one is two levels down at
`athena-os/.claude/`. Corroborated by contrast inside this same session: `.mcp.json`
sits **at** the workspace root and loaded fine — five `neighborhood` calls — so cwd
is demonstrably where this client reads project config.

**(2) Schema — LATENT SECOND FAULT, failure mode confirmed.** Piping a payload to the
bare interpreter (what an ignored `args` produces) exits **0 with no output**, because
a JSON object literal is a valid Python expression statement. Silently
indistinguishable from an unregistered hook. Unobservable until (1) is fixed; will
bite immediately after.

**(3) `cat` routing — REAL, NOT CAUSAL.** Auto mode instructs Bash reads, and a `Read`
matcher cannot see those (1 `Read` vs 4+ `cat` here). **Disproven as the mechanism by
a counterexample in each session:** a genuine `Read` occurred both times and was not
intercepted. It stands as a reliability limit — the hook's reach depends on a
tool-choice heuristic it does not control — which is a design question, not a patch.

**The uncomfortable part.** 4b closed only after `.mcp.json` was moved **to** the
workspace root, and that reasoning is written into its own closure row. Checkpoint 5
then put its config two levels below that root. Same defect class, one checkpoint
apart, with the fix already on the page above it.

**Flag 4 (cluster labels) and flags 2, 3, 5, 6 remain open.** No fix applied to the
wiring in this pass, per instruction.
