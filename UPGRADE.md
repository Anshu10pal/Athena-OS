# ATHENA OS v2 — "Jarvis layer" upgrade

## How to apply
Extract this zip OVER your existing D:\Athena\athena-os folder (overwrite all).
Safe: your `.env`, `athena.db`, `qdrant_data/` and `venv/` are not in the zip and won't be touched.
The backend proxy fixes you applied manually (httpx verify=False, config extra=ignore) are now baked in.

Then restart the backend: `python run.py` (one new endpoint: GET /api/briefing).
No new Python packages needed. Frontend changes activate when Node.js arrives.

## What's new

**Backend**
- `GET /api/briefing` — Athena's personalized daily briefing (LLM-generated from your real stats)
- `core/llm.py` — corporate-proxy-ready (verify=False, 60s timeout) baked in
- `core/config.py` — `extra = "ignore"` baked in

**Frontend — Tier 1 (atmosphere)**
- `ParticleField` — 80-particle brass plexus background; drifts when idle, gravitates when listening, orbits when thinking, radiates (audio-reactively) when speaking
- `BootSequence` — typed "ATHENA OS" + systems-check boot screen, once per session, click to skip
- Typewriter cursor on streaming chat responses

**Frontend — Tier 2 (reactive HUD)**
- `VoiceOrb` is now audio-reactive: core scales + glows with live mic amplitude (Web Audio AnalyserNode), and with Athena's TTS output when voice replies are on
- `HudTelemetry` — bottom-right strip: live state, active agent, TTFB latency, tokens/sec
- `CommandPalette` — Ctrl+K anywhere: jump to pages or type free text to ask Athena (routes to chat and auto-sends)

**Frontend — Tier 3 (cinematic)**
- `ConstellationRoadmap` — roadmap as a star map: dependency lines draw themselves, completed stars glow, active star pulses; click stars to start/complete. Toggle between Constellation and List views
- `LevelUpOverlay` — expanding brass rings + LEVEL N splash whenever XP crosses a 500 boundary (missions and roadmap both trigger it)
- Daily briefing on the Dashboard — typed out character by character next to the orb, refreshed once per day
- Sound design — soft chime (mission), unlock arpeggio (roadmap node), level-up fanfare, low hum while thinking. All Web Audio oscillators, no files. Mute toggle in the topbar; preference remembered

## Voice replies
The speaker toggle in Chat plays Athena's answers aloud via /api/voice/speak.
Requires the Phase 4 voice install (requirements-voice.txt + a Piper voice model); silently does nothing until then.
