# Communication Gym — Drop 4: Speaking folded in (ALL FOUR LIVE)

The gym is complete. Backend + frontend verified compiling & building.

## Apply
backend: restart — on first boot it runs a ONE-TIME BACKFILL that mirrors your existing
         speeches into the gym (idempotent; safe to restart repeatedly).
frontend: npm install && npm run dev   ·   Render: push (backfill runs on deploy boot)

## What shipped — Speaking unified
- The Oratory Deck stays the proven Speaking engine (not rebuilt — your live users keep
  the flow they know).
- DATA UNIFICATION: every speech now ALSO writes a CommunicationSession(modality="speaking"),
  so the radar's Speaking spoke comes from the same place as the other three.
- HISTORY MIGRATION: a one-time, idempotent backfill mirrors all your past SpeechSessions
  into the gym on startup — nothing is orphaned, and reruns don't duplicate (matched on
  user + timestamp).
- The Speaking tile now opens an in-gym panel (last score + launch button) instead of
  silently redirecting — so all four tiles feel like one roof.

## The complete gym
- Writing   — prompt → response → 6 dims (3 measured locally / 3 LLM-evaluated)
- Reading   — timed passage → WPM + comprehension/inference/vocab/main-idea
- Listening — server-side TTS, single play, text withheld → reception vs inference
- Speaking  — oratory engine, now feeding the unified radar
- Radar     — all four roll into one Communication score on the Digital Twin
- Review    — missed vocab/concepts across modalities feed spaced repetition

## Honest notes
- The Speaking score is the average of the oratory dimensions (0-10) scaled to 0-100.
- Backfill touches all users' speeches once; trivial at your scale.
- The Oratory Deck page still exists at /oratory and works standalone too.
