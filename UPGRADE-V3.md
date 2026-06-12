# ATHENA OS v3 — Command Hub, Gated Learning & Oratory Deck

## Apply
Extract OVER your existing folder (overwrite all). Your `.env`, `athena.db`, `qdrant_data/`, `venv/`,
`node_modules/` are untouched. Then:
- Backend: restart `python run.py` (auto-migrates the interview table, no manual SQL)
- Frontend: `npm run dev` (no new packages needed)

## What's new

### Command Hub (new home at /)
Post-login launcher: central orb (click it -> chat) with daily briefing typed beneath,
digital-twin arc gauges, six module stations with LIVE stats deploying around it.
Esc returns to Hub from anywhere. Dashboard page retired — everything lives on the Hub.

### Roadmap: node dossiers + gated assessments
- Click any unlocked node (constellation or list) -> dossier drawer:
  personalized BRIEFING (generated once, cached), STUDY MATERIAL
  (community links from github.com/Anshu10pal/athena-content + hallucination-proof search links),
  "+ suggest a resource" -> pre-filled GitHub issue (zero credentials).
- Nodes can no longer be completed manually. "Begin assessment" -> 15/20/25 MCQs by node weight,
  pass >= 70% -> completed, XP 150–225 scaled by score, weak topics listed on fail.
- New "skip — I already know this" option: unlocks dependents, no XP.

### Interview Arena: two stages
Stage 1: 10 timed MCQs (30s each, auto-advance on timeout).
Stage 2: 4 adaptive descriptive questions.
Scorecard blends measured MCQ accuracy into technical_accuracy.

### Oratory Deck (new page)
Toastmasters Table Topics: mode (classic/professional/wildcard) -> topic draw (decrypt reveal)
-> 30s think -> 1/2/3-min speak with live audio-reactive orb and green/amber/red timing-card border
-> verbatim transcription (faster-whisper, word timestamps, filler-preserving prompt) ->
Ah-Counter report (fillers/min, crutch words, WPM, stall pauses — MEASURED) +
Evaluator notes (structure/relevance/vocabulary/delivery — AI JUDGED) + filler-rate trend chart.
XP rewards improvement over your own last session. Requires: pip install faster-whisper

### Missions: rotation
Completing a directive immediately deploys a replacement ("NEW DIRECTIVE" slide-in). Always 3 active.

### Sci-fi styling pass
Corner brackets on every card · DecryptText headings · AnimatedNumber stats ·
status strip (UTC clock, session timer, provider dots) · arc gauges · skipped-state visuals.

### Performance (baked in)
Commander runs intent detection + memory retrieval in parallel; embedding model warms up at
startup in the background. Watch TTFB drop in the HUD strip.

## Backend API added
GET  /api/roadmap/{id}/node/{nid}/dossier
POST /api/roadmap/{id}/node/{nid}/assessment/start
POST /api/roadmap/assessment/{aid}/submit
POST /api/interview/mcq
POST /api/oratory/topic | /analyze | GET /history
