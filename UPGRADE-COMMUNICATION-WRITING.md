# Communication Gym — Drop 1: Writing modality

The first pillar of the communication gym. Backend + frontend, verified compiling & building.

## Apply
```
# backend — migrations auto-run on startup (adds communication_sessions table + review_items.kind/detail)
cd backend && (activate venv) && python run.py
# frontend
cd frontend && npm install && npm run dev
```
On Render: push, it auto-migrates on boot (the main.py migration block is Postgres-safe).

## What shipped
- **Communication page** (sidebar → "Communication Gym", or Ctrl+K): four-tile launcher
  (Listening · Speaking · Reading · Writing) + difficulty selector (Beginner/Intermediate/
  Advanced) + the four-spoke radar with a blended Communication score.
- **Writing drill — fully working**:
  - Athena generates a fresh general-communication prompt at your chosen difficulty.
  - You type a response; word counter tracks against the target.
  - Scorecard with SIX dimensions, each tagged MEASURED or EVALUATED honestly:
      • Vocabulary, Precision, Clarity  → MEASURED locally (no LLM, no network) by a new
        dependency-free text-metrics engine (lexical diversity, readability, hedge/passive density).
      • Grammar, Structure, Tone        → EVALUATED by the LLM.
    (Note: I changed Grammar from "measured" in the mockup to "evaluated" — real grammar
     checking needs a heavy Java library; the honest tag is evaluated.)
  - Athena feedback + one concrete tip, grammar fixes, vocabulary upgrades.
  - **Missed vocab/grammar items feed the Review Queue** as spaced-repetition cards
    (they generate their own recall questions when due).
- **Radar feeds the dashboard**: analytics now returns communication_score.
- **Speaking tile** routes to your existing Oratory Deck for now; **Listening & Reading**
  show a "coming next" panel — built one modality at a time so your live app stays stable.

## Storage
Only a small CommunicationSession row per drill (prompt + response + scores). Passages/prompts
are generated and discarded. Negligible footprint, as planned.

## Next modalities (when you're ready)
Reading (timed passage + WPM + quiz), then Listening (Edge-TTS single-play + inference),
then fold Speaking in properly with history migration.
