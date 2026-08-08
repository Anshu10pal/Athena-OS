# Codebase Agent — Ranking Methodology

How `POST /api/repos/{id}/rank` turns an ingested repo's `code_files`/`code_imports`
into the ordered reading list on `/repos/:id`. Implementation:
`backend/app/services/codebase/ranking.py`. Weights config: `backend/config/ranking_weights.yaml`.

Zero LLM calls. Every signal below is deterministic local computation over the
import graph (built in Phase B) and, optionally, real git history.

## 1. The import graph

A `networkx.DiGraph` is rebuilt from the database on every rank run — it is
never stored as a blob, so it's always consistent with the latest ingest.

- **Nodes**: every `code_files` row for the repo.
- **Edges**: one edge `from_file → to_file` per **resolved** `code_imports` row
  (`to_file_id IS NOT NULL`), deduplicated. An edge means "`from_file` imports
  `to_file`." Unresolved imports (external packages, stdlib, dynamic
  `import()`, and the other gaps listed in the ingest report's `blind_spots`
  field — see `IngestReport` in `backend/app/services/codebase/ingest.py`)
  contribute no edge.
- Multiple import statements between the same pair of files (e.g. two separate
  `from x import a` / `from x import b` lines) collapse to a single edge —
  fan-in counts *distinct files that import you*, not *import statements*.

## 2. Graph signals (always available)

| Signal | Definition |
|---|---|
| `fan_in` | In-degree: how many other files import this file. |
| `fan_out` | Out-degree: how many other files this file imports. |
| `pagerank` | PageRank over the graph above, edge direction `importer → imported` — the same convention as a citation graph, so a file imported by a few important files outranks one imported by many unimportant ones. |
| `is_entry_point` | `True` if `fan_in == 0`, **or** the file's basename is in a fixed list: `main.py`, `__main__.py`, `manage.py`, `wsgi.py`, `asgi.py`, `cli.py`, `app.py`, `index.{ts,tsx,js,jsx}`, `main.{ts,tsx}`, `server.{ts,js}`. A heuristic, not a guarantee — some real entry points won't match either check, and some zero-fan-in files are just dead code, not entry points. |

**PageRank implementation note**: this is a hand-rolled plain power-iteration
PageRank (damping `0.85`, up to 100 iterations, convergence tolerance `1e-8`,
dangling-node mass redistributed uniformly across all nodes each iteration) —
*not* `networkx.pagerank()`. That function hard-imports `scipy` in networkx
3.4 with no pure-Python fallback, and this project deliberately avoids
compiled dependencies (the corporate proxy makes them painful to install).
Numerically it will not match `networkx.pagerank()` bit-for-bit, but it
converges to the same fixed point for the same graph.

## 3. History signals (optional, degrading)

`commit_count`, `distinct_authors`, `days_since_last_change` come from one
`git log --format=@@%an|%aI --numstat -- .` call per rank run (not one call
per file), run with `cwd` set to the repo's registered local path. Commits
are attributed to whichever path git reports for each `--numstat` line.

**Nested repos**: if the registered local path is a subdirectory of a larger
git working tree, `git log`'s reported paths are still relative to that
larger tree's root, not to the registered path. The offset between them
(via `git rev-parse --show-toplevel`) is computed once and stripped from
every reported path before matching against `code_files.path`. The pathspec
passed to `git log` itself is always `.` (meaning "everything under cwd") —
it must never be the offset itself, since `cwd` is already inside the
subdirectory (an early version of this code doubled the offset and silently
found nothing; there's a regression test for it).

**Renames**: `--numstat` (unlike `--stat`) never emits the ambiguous
`{old => new}` rename syntax, so parsing is never wrong — but commits made
*before* a rename stay attributed to the old path forever. A renamed file's
`commit_count`/`distinct_authors` will under-count relative to its real history.

### Two different kinds of "no data"

| Situation | Result | Why |
|---|---|---|
| `git.exe` not resolvable at all | Whole run: `commit_count`/`distinct_authors`/`days_since_last_change` = `null` for every file, `reduced_confidence = true` | History is genuinely unknown for the whole repo. |
| `git log` fails or returns nothing (no `.git`, no commits) | Same as above | Same reasoning — nothing to attribute to any file. |
| `git log` succeeds, but *this one file* has zero commits (e.g. created and never committed) | `commit_count = 0`, `distinct_authors = 0`, `days_since_last_change = null`, `reduced_confidence = false` | This is a known fact, not missing data — the rest of the repo's history is real, so the whole run isn't degraded just because one file is new. |

This distinction mattered in practice: an early version treated both cases
identically as `null`, which meant every uncommitted file in a repo (e.g. a
feature branch mid-development) flipped `reduced_confidence` for the *entire*
ranking run even though real history existed for everything else.

## 4. Normalizing signals

Before weighting, every raw signal is min-max normalized to `[0, 1]`
**across this repo's own files only** — scores are relative to the repo being
ranked, not comparable across different repos. If every file has the same
value for a signal (e.g. a graph with no edges at all), that signal
normalizes to a flat `0.5` for everyone rather than dividing by zero.

`days_since_last_change` is inverted after normalizing (`recency = 1 - normalized_days`)
so that *more recently changed* files score higher, matching every other
signal's "higher is more important" direction.

## 5. Weights and the composite score

Weights live in `backend/config/ranking_weights.yaml`:

```yaml
weights:
  fan_in: 0.35
  pagerank: 0.30
  is_entry_point: 0.15
  commit_count: 0.10
  distinct_authors: 0.05
  recency: 0.05
```

These should sum to `1.0`. A missing or unreadable config file falls back to
these exact defaults rather than crashing ranking. Any key you omit from the
YAML keeps its default value — you only need to list the ones you're changing.

**Normal case** (git history available):

```
score = 0.35·norm(fan_in) + 0.30·norm(pagerank) + 0.15·is_entry_point
       + 0.10·norm(commit_count) + 0.05·norm(distinct_authors) + 0.05·norm(recency)
```

**Reduced-confidence case** (no history available): the three history
weights (`commit_count` + `distinct_authors` + `recency`, summing to `0.20`
by default) are redistributed *proportionally* across the three graph
weights, so the total stays `1.0` instead of silently scoring history as
zero-and-counted:

```
new_weight[k] = weight[k] × (1 + history_weight_sum / graph_weight_sum)   for k in {fan_in, pagerank, is_entry_point}
```

With the defaults, `history_weight_sum = 0.20`, `graph_weight_sum = 0.80`,
so each graph weight is scaled by `1.25` (e.g. `fan_in` effectively becomes
`0.4375`) — the same 0.35 : 0.30 : 0.15 ratio, just stretched to fill the
full budget.

## 6. What gets stored

Every individual signal is persisted per file in `code_file_ranks` —
`fan_in`, `fan_out`, `pagerank`, `is_entry_point`, `commit_count`,
`distinct_authors`, `days_since_last_change`, `reduced_confidence`, and the
final `score` — not just the composite. A rank run replaces all rows for
that repo wholesale (no accumulation across runs); re-ranking with tuned
weights never requires re-ingesting the repo.

## 7. Tuning weights

Edit `backend/config/ranking_weights.yaml` and call `POST /api/repos/{id}/rank`
again (no re-ingest needed — ranking reads the already-parsed `code_files`/
`code_imports`). If you compare results before and after a weight change
against a hand-authored answer key, report both runs, not just the tuned one
presented as if it were the only attempt.

## 8. Validating against a hand-authored answer key

`backend/scripts/validate_ranking.py` compares this tool's top-20 for a repo
against a hand-authored, independent reading-list answer key (deliberately
not scaffolded by this tool — the point is an unbiased ground truth):

```
python scripts/validate_ranking.py <repo_id> <answer_key_path>
```

Answer key format: one file path per line, most-important first, list
markers/backticks optional (see the script's own docstring for exact
parsing rules). It reports Overlap@20, Overlap@10, a Spearman rank
correlation computed over the intersection of both top-20 lists (hand-rolled,
same no-`scipy` constraint as PageRank), a go/no-go verdict at the brief's
Overlap@20 ≥ 12 threshold, and the specific files each side has that the
other doesn't. There is no API endpoint for this — it's a one-off validation
exercise, run from the CLI against `docs/reading-list-answer-key.md` once
that file exists.

## Known limitations

- `is_entry_point` is a heuristic (zero fan-in or a filename match) — it can
  both miss real entry points and flag dead code as one.
- The hand-rolled PageRank is not identical to `networkx.pagerank()`, by
  design (see §2).
- History signals undercount across file renames (see §3).
- History collection assumes one flat `git log` walk is representative;
  it does not account for `.gitignore`d files that were tracked in the past,
  submodules, or shallow clones (a shallow clone's truncated history will
  under-count older files — this is exactly why the `pygit2` fallback path
  in `git_ops.py` always does a full clone, never shallow).
- Everything here scores **files**, not symbols or subsystems — there is no
  clustering, summarization, or semantic grouping in this tool by design.
