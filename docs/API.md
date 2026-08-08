# ATHENA OS — API Reference

The backend exposes a REST + SSE API. Interactive Swagger docs at **http://127.0.0.1:8000/docs** when running.

All non-auth endpoints require `Authorization: Bearer <JWT>` header.

## Auth

### `POST /api/auth/register`
```json
{ "name": "Anshuman", "email": "you@example.com", "password": "..." }
```
Returns `{ access_token, token_type: "bearer" }`. Streak initialized to 1.

### `POST /api/auth/login`
OAuth2 password form: `username=email&password=...`. Increments streak if last_active = yesterday, resets to 1 if older.

### `POST /api/auth/change-password`
```json
{ "current_password": "...", "new_password": "..." }
```
Verifies current password. Min 6 chars on new.

### `GET /api/auth/me`
Returns full user profile.

## Profile

### `PATCH /api/profile`
Partial update. Any of:
```json
{
  "name": "...", "experience_level": "intermediate",
  "current_role": "...", "target_role": "AI Architect",
  "learning_goals": "...", "skills": {"Python": 4},
  "voice": "en-IN-NeerjaNeural"
}
```

## Chat (streaming)

### `POST /api/chat/stream`
```json
{ "message": "Explain LangGraph checkpointing", "history": [{"role":"user","content":"..."}] }
```
Returns Server-Sent Events:
```
data: {"type":"meta","intent":"learn"}
data: {"type":"token","text":"Check"}
data: {"type":"token","text":"pointing in"}
...
data: {"type":"done"}
```
On error: `data: {"type":"error","message":"..."}`. Exchange is persisted to vault and memory.

## Briefing

### `GET /api/briefing`
Returns `{ "text": "Good morning Anshuman. Day 2 streak. Today's focus: Deep Learning..." }`. Generated from real stats.

## Roadmap

### `POST /api/roadmap/generate`
```json
{ "target_role": "AI Architect", "current_skills": ["Python", "FastAPI"] }
```
Runs the LangGraph workflow. Returns the created roadmap.

### `GET /api/roadmap`
List all user's roadmaps (root + sub-maps).

### `POST /api/roadmap/{roadmap_id}/node`
Add a custom topic. `{ "title": "Prompt Engineering" }`. Athena fills description + skills.

### `DELETE /api/roadmap/{roadmap_id}/node/{node_id}`
Remove a node. Dependents auto-rewire.

### `PATCH /api/roadmap/{roadmap_id}/node`
```json
{ "node_id": "n3", "status": "skipped" }
```
Status options: `available`, `in_progress`, `skipped`. (Note: `completed` is not allowed — assessments gate completion.)

### `GET /api/roadmap/{roadmap_id}/node/{node_id}/dossier`
```json
{
  "node": {...},
  "definition": "...",
  "eli5": "...",
  "briefing": "...",
  "submap_id": null,
  "community_resources": [...],
  "generated_links": [...],
  "suggest_url": "https://github.com/.../issues/new?...",
  "question_count": 20,
  "pass_threshold": 70
}
```

### `POST /api/roadmap/{roadmap_id}/node/{node_id}/expand`
Generate (or return) the granular sub-roadmap for one node.

### `POST /api/roadmap/{roadmap_id}/node/{node_id}/assessment/start`
Returns `{ assessment_id, questions: [{q, options, topic}], pass_threshold }`. Answer indices not exposed.

### `POST /api/roadmap/assessment/{assessment_id}/submit`
```json
{ "answers": [0, 2, 1, 3, ...] }
```
Returns score, pass/fail, per-question correctness, weak topics, updated nodes, parent auto-completion info.

## Interview

### `POST /api/interview/start`
```json
{ "role": "AI Engineer", "job_description": "" }
```
Returns 10 MCQs for stage 1.

### `POST /api/interview/mcq`
```json
{ "session_id": 1, "answers": [0, 1, 2, ...] }
```
Grades MCQs, returns first descriptive question.

### `POST /api/interview/answer`
```json
{ "session_id": 1, "answer": "...", "finish": false }
```
`finish: true` terminates early. Hard cap at 10 descriptive questions. Final response includes full MCQ review + transcript + 5-dimension scorecard.

## Oratory

### `POST /api/oratory/topic`
```json
{ "mode": "classic" }   // classic | professional | wildcard
```
Returns `{ topic, hint }`. Avoids your last 12 topics.

### `POST /api/oratory/analyze` (multipart)
Fields: `file` (audio), `topic`, `mode`, `target_secs`. Returns:
```json
{
  "transcript": "...",
  "metrics": {
    "duration_secs": 87.2, "target_secs": 60, "words": 215, "wpm": 148,
    "filler_count": 12, "filler_rate_per_min": 8.3,
    "filler_breakdown": [{"word":"um","count":7}, ...],
    "hedge_breakdown": [{"word":"i think","count":3}],
    "weak_words": [...], "crutch_words": [...],
    "wpm_timeline": [{"t":0,"wpm":135}, ...],
    "talk_ratio": 0.82, "pause_count": 5, "stall_pauses": 2, "longest_pause_secs": 1.8
  },
  "scores": {
    "structure": 7, "relevance": 8, "vocabulary": 6, "delivery": 7,
    "feedback": "...", "tip": "...",
    "grammar_fixes": [{"original":"...","corrected":"..."}],
    "vocab_suggestions": [{"used":"very","try":"considerably"}]
  },
  "xp_gained": 75, "improved": true
}
```

### `GET /api/oratory/history`
Last 50 sessions for trend chart.

## Missions

### `GET /api/missions/today`
Returns today's missions. Tops up to 3 active if you have fewer.

### `POST /api/missions/{id}/complete`
Awards XP, levels up skills, immediately generates a replacement directive.

## Presentation

### `POST /api/presentation/analyze` (multipart)
Field: `file` (.pptx or .pdf). Returns structured deck analysis: overall score, storytelling, business impact, technical depth, slide-by-slide feedback, speaker notes, executive summary.

## Voice

### `POST /api/voice/transcribe` (multipart)
Field: `file` (audio). Returns `{ "text": "..." }`. Uses faster-whisper.

### `POST /api/voice/speak`
```json
{ "text": "..." }
```
Returns audio (`audio/mpeg` if Edge-TTS, `audio/wav` if Piper). 501 if both unavailable — frontend then uses browser `speechSynthesis`.

## Vault

### `POST /api/vault/notes`
```json
{ "title": "...", "content": "...", "kind": "note" }
```

### `GET /api/vault/entries`
Last 100 entries, all kinds (chat, note, interview, presentation, speech, research).

### `GET /api/vault/search?q=...`
Semantic search over your vector memory. Top 8 hits with relevance scores.

## Analytics

### `GET /api/analytics/dashboard`
Drives the Command Hub. Returns XP, level, streak, roadmap progress, interview readiness, presentations analyzed, speech count, vault entries, oratory filler rate, skills, digital twin metrics.

## Codebase Agent

A separate feature from the rest of this app: ingests a git repo (clone or local checkout), builds its import graph, and produces a ranked reading list, an architecture map, and dependency clusters — zero LLM calls anywhere in this section. Full design/status doc: `docs/codebase-agent-handoff.md`.

### `GET /api/repos`
List all registered repos.

### `POST /api/repos`
```json
{ "url": "https://github.com/owner/repo.git", "source_root": null }
```
Or `{ "local_path": "D:\\path\\to\\checkout" }` instead of `url` — exactly one of the two, not both. `source_root` (optional) scopes ingestion to a subdirectory of the checkout.

### `GET /api/repos/{id}`
Single repo's metadata (host/owner/name, `source_kind`, `last_ingested_at`, `file_count`, `seed_exclude_paths`, etc.).

### `PUT /api/repos/{id}/seed-exclude-paths`
```json
{ "seed_exclude_paths": ["scripts/", "tools/cron/"] }
```
Per-repo override: prefix-matched paths excluded from seeding weighted PageRank (they still earn the entry prior, just don't carry teleport mass) — every repo has some auxiliary surface no ecosystem-wide marker catches.

### `POST /api/repos/{id}/resync`
Fetch + checkout latest (clone-kind repos only; 400 on a `local` repo).

### `POST /api/repos/{id}/ingest`
Synchronous parse + import-graph build. Returns a report (`files_total`, `files_parsed`, `imports_resolved`, `promoted_python_roots`, `blind_spots`, etc.). 409 if this repo has an ingest/rank already in flight.

### `POST /api/repos/{id}/rank`
Synchronous ranking with the `legacy` scorer (weighted-sum composite). 409 if busy. `weighted_pagerank`/`rrf` scorers are computed by their own service functions, not yet a distinct endpoint each — call `POST /rank` then read `GET /ranking?scorer=weighted_pagerank` after a job that runs all three, or see `jobs.py`.

### `GET /api/repos/{id}/ranking?scorer=legacy`
One row per file for the given scorer (`legacy` | `weighted_pagerank` | `rrf`), ordered by stored rank. Includes `reduced_confidence` (repo-wide) and each file's `subsystem_modularity_id`/`subsystem_louvain_id`.

### `GET /api/repos/{id}/graph?scorer=&level=directory&limit=&language=&path_prefix=&min_score=`
Nodes + edges for the Architecture/Matrix/Layers views. `level=directory` (default) returns aggregated directory nodes (`kind`, `cluster_id`, `cluster_purity`, cross-directory edges); `level=file` returns the underlying file-level graph. `limit` caps directories/files by rank *after* aggregation, never before — filtering never distorts the aggregate.

### `GET /api/repos/{id}/files/{file_id}/neighbors?scorer=`
Importers/imports for one file, each direction capped independently (`NEIGHBORS_ENDPOINT_CAP`) with a `*_total_before_cap` field.

### `POST /api/repos/{id}/jobs`
Starts a background resync→ingest→rank job. Returns `{ job_id }`.

### `GET /api/repos/{id}/jobs/latest`
Most recent job's status/progress/result for this repo.

### `GET /api/repos/{id}/jobs/{job_id}/stream`
Server-Sent Events, same wire shape as `/api/chat/stream`: `{"type":"progress",...}` / `{"type":"done","result":{...}}` / `{"type":"error","message":"..."}`.

### `POST /api/repos/{id}/subsystems`
Runs dependency-cluster detection (modularity + Louvain community detection over the resolved import graph) and persists both. Returns per-algorithm cluster counts, the modularity⇄Louvain agreement number, and cycle-cluster coherence findings. 409 if busy. These are measured coupling groups, not confirmed architectural subsystems — see `docs/external-validation-eslint.md`'s Round 3 for why that distinction is load-bearing.

### `GET /api/repos/{id}/overview`
Everything the repo landing page shows: identity + extracted description, aggregate counts (files, lines, directories, symbols by kind, imports + resolution rate, language/category breakdowns), a structural health score with its per-factor breakdown, and change hotspots. Pure read over what ingest/rank/clustering already persisted — no filesystem walk, no re-parse.

Two honesty properties are part of the contract, not presentation details:
- `health` is **structural** health, not defect prediction. This system holds no defect data (no issue-tracker linkage, no bug-fix commit classification), and the payload carries its own `caveat` string saying so. Each factor reports `available`; an unmeasurable factor is `value: null` and is **excluded from the score's weighted mean** rather than counted as zero (e.g. `documentation` is Python-only, because the JS/TS parser does not extract JSDoc — scoring JS symbols as undocumented would measure this tool's parser, not the code).
- `hotspots` is a churn × fan-in **risk proxy**, not measured defects. When churn has no variance — every file reporting the same `commit_count`, the shallow-clone case — it returns `available: false` with a `reason` instead of ranking files by a constant.

### `POST /api/repos/{id}/subsystems/hdbscan`
Runs a third, separately-triggered clustering algorithm — HDBSCAN over FastEmbed embeddings (local, `BAAI/bge-small-en-v1.5`, no network call) of each file's symbol signatures + docstrings, rather than the import graph. Slower than `POST /subsystems` (real CPU embedding work — seconds per hundred files, not near-instant graph math), so it stays its own button/endpoint. Returns `agreement_with_modularity` (null if modularity hasn't run yet), its own `cycle_coherence`, and embedding timing/coverage. 409 if busy. **Validated (docs/external-validation-eslint.md's Round 4) to currently underperform modularity/Louvain on a repo with many structurally-similar files** (ESLint's ~294 individual lint rule implementations collapsed into one 81%-of-repo mega-cluster) — reported honestly, not smoothed over; treat as experimental, not a proven improvement.

### `GET /api/repos/{id}/subsystems?algorithm=modularity`
Persisted clusters for one algorithm (`modularity` | `louvain` | `hdbscan`) — read-only, never recomputes. Includes `agreement`, `cycle_coherence`, and `unclustered_count` (for `hdbscan`, `agreement` means agreement WITH modularity, not modularity⇄Louvain).

### `GET /api/repos/{id}/subsystems/{subsystem_id}/members`
Real files belonging to one cluster.

### `PATCH /api/repos/{id}/subsystems/{subsystem_id}`
```json
{ "custom_label": "Auth" }
```
Renames a cluster. Survives the next `POST /subsystems` run if the new clustering's best-overlapping cluster shares ≥50% of the old cluster's members; otherwise resets to the default label.
