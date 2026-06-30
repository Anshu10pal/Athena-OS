# Communication Gym — Drop 3: Listening modality

Adds Listening. Three of four modalities now live. Backend + frontend verified building.

## Apply
backend: restart (no new tables — reuses communication_sessions)
frontend: npm install && npm run dev   ·   Render: push

## What shipped — Listening drill
- Athena generates a passage and SYNTHESIZES IT TO AUDIO SERVER-SIDE (Edge-TTS). The
  passage TEXT IS NEVER SENT TO THE BROWSER — so it's a genuine listening test, not a
  reading one. Audio returns as base64 and plays once.
- SINGLE PLAY: no replay button. Listen closely, then the quiz opens automatically when
  the audio ends.
- Quiz scores RECEPTION (stated facts + detail retention) and INFERENCE (what's implied)
  SEPARATELY, exactly as specced — both shown as GRADED bars.
- Missed key terms feed the Review Queue as concept cards.
- Listening score flows into the radar + Digital Twin automatically.

## TTS fallback
If Edge-TTS is blocked or unavailable on the server, the endpoint falls back to handing
the text to the browser's speech synthesizer (which reads it aloud WITHOUT displaying it).
You'll see a small "using your browser's voice" note when that path is active.
NOTE: on Render, confirm `edge-tts` is in requirements and outbound audio works; if the
free instance blocks it, the browser-voice fallback keeps the drill usable.

## Status of the four tiles
- Writing   — live
- Reading   — live
- Listening — live (this drop)
- Speaking  — routes to your existing Oratory Deck

## Last step (when ready)
Fold Speaking in as a proper tab with oratory-history migration, so all four live under
one roof and the radar's Speaking spoke comes from in-gym sessions.
