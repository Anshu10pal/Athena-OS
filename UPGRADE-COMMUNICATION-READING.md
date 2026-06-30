# Communication Gym — Drop 2: Reading modality

Adds Reading on top of Writing. Backend + frontend verified compiling & building.

## Apply
backend: restart (auto-migrates; no new tables needed — reuses communication_sessions)
frontend: npm install && npm run dev   ·   Render: push, auto-migrates on boot

## What shipped — Reading drill
- Athena generates an original passage at your difficulty (Beginner ~120w / Intermediate
  ~200w / Advanced ~320w), plus a 6-question quiz.
- TIMED READ: a stopwatch runs while you read; clicking "Done reading" computes your
  WPM (measured client-side from word count ÷ read time).
- QUIZ across four objective types — comprehension, inference, vocabulary, main-idea —
  with a question navigator so you can jump around before submitting.
- SCORECARD: overall reading score + WPM side by side, then per-dimension bars tagged
  GRADED (objective MCQ, not LLM opinion).
- Missed VOCABULARY items feed the Review Queue as spaced-repetition cards.
- Reading score flows into the radar + Digital Twin automatically (no extra wiring —
  the radar reads the latest CommunicationSession per modality).

## Status of the four tiles
- Writing  — live
- Reading  — live (this drop)
- Speaking — routes to your existing Oratory Deck
- Listening — "coming next" panel

## Next
Listening (Edge-TTS single-play passage → reception + inference scored separately),
then fold Speaking in properly with oratory-history migration.
