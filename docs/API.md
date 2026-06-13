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
