# ATHENA OS — Adaptive AI Learning & Career Platform

Local-first, voice-enabled, multi-agent learning platform. FastAPI + LangGraph backend, React/Vite/TypeScript frontend, Gemini (primary) + Groq (fallback) LLM router — **$0/month**.

---

## 1. Get your free API keys (no credit card)

| Provider | Where | What you get |
|---|---|---|
| **Gemini** (primary) | https://aistudio.google.com → "Get API key" | ~1,500 req/day, 1M context, vision included |
| **Groq** (fallback) | https://console.groq.com → "API Keys" | Llama 3.3 70B, very fast, ~1,000 req/day |

Both keys go in `backend/.env`. The router (`app/core/llm.py`) uses Gemini first and silently falls back to Groq on rate limits — short internal calls (intent detection, scoring) go to Groq first for speed.

## 2. Backend setup (Windows PowerShell)

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env: paste GEMINI_API_KEY, GROQ_API_KEY, and a random SECRET_KEY
python run.py
```

Backend runs at http://127.0.0.1:8000 (interactive docs at /docs).
First chat/vault call downloads a small embedding model (~80 MB, one time).

> Use **Python 3.12** (pin it on Render later with `runtime.txt`, same as your other projects).

## 3. Frontend setup

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — Vite proxies `/api` to the backend automatically.

## 4. Voice setup (optional — Phase 4)

The app works fully with text + push-to-talk-to-text. For local STT/TTS:

```powershell
cd backend
pip install -r requirements-voice.txt
```

- **STT**: faster-whisper `base` model downloads automatically on first use (CPU int8, fine without GPU).
- **TTS**: download a Piper voice (e.g. `en_US-lessac-medium.onnx` + `.json` from the Piper voices repo on Hugging Face) into `backend/voices/`, or set `PIPER_VOICE` in the environment.
- **Wake word** ("Hey Athena"): `voice_listener/wake_word.py` is the desktop-listener stub using OpenWakeWord — Phase 4 work.

---

## What's implemented vs. stubbed

**Working now**
- JWT auth (register/login/streak tracking), profile
- Commander agent: intent detection → routes to Learning / Research / Memory / General agents
- SSE streaming chat with memory retrieval + auto-save to long-term memory
- Vector memory: embedded Qdrant + FastEmbed (no Docker, no torch, CPU-only)
- Roadmap engine: **LangGraph workflow** (generate → validate/repair) with locked/available/in-progress/completed node states, dependency unlocking, XP
- Interview Arena: 6-question adaptive interview + 5-dimension scorecard
- Presentation Arena: .pptx/.pdf upload → slide feedback, speaker notes, exec summary
- Knowledge Vault: notes + semantic search over everything you've done
- Missions: LLM-generated daily missions with XP rewards
- Analytics dashboard + Digital Twin metrics
- Voice Orb (idle/listening/thinking/speaking), push-to-talk recording

**Stubbed / next phases**
- Phase 2: Debate agent, audience simulation (Boardroom), whiteboard/vision (use Gemini vision — free tier handles images)
- Phase 3: Spaced repetition + knowledge decay, achievements, animated skill tree
- Phase 4: Local voice pipeline polish + wake word listener, speaker mode
- Phase 5: Knowledge graph (currently SQLite/JSON; Neo4j can slot in behind `services/`)

## Architecture map

```
backend/app/
  core/llm.py          <- Gemini->Groq router (one OpenAI SDK, two base URLs)
  agents/commander.py  <- intent detection + routing
  agents/roadmap_graph.py <- LangGraph: generate -> validate
  agents/prompts.py    <- every agent's system prompt in one place
  services/vector_store.py <- embedded Qdrant + FastEmbed
  api/                 <- auth, chat (SSE), roadmap, interview, presentation, vault, missions, analytics, voice
frontend/src/
  components/VoiceOrb.tsx  <- the astrolabe orb (4 states)
  pages/               <- Dashboard, Chat, Roadmap, Interview, Presentation, Vault
```

## Content library (modules, topics, roadmaps)

Curated content lives as YAML under `content/modules/*.yaml` and `content/roadmaps/*.yaml` — Git is
the durable record. An idempotent seeder (`app/services/seed.py`) loads it into the DB on every
startup; `POST /api/content/export` writes the current DB state back out to those same files so
curation (saving a real link over a search-intent one) can be committed. Schema is Alembic-owned
(`backend/alembic/`) — `alembic upgrade head` runs automatically on startup, replacing the old
hand-written `ALTER TABLE` list.

**Uploaded resource files are not durable on Render.** `POST /api/topics/{id}/resources/upload`
stores files under `RESOURCES_DIR` (default: a per-OS app-data directory outside the repo, via
`platformdirs` — see `backend/app/core/config.py`), `{module_slug}/` beneath that. That's fine
locally, but Render's default web service filesystem is ephemeral — uploads are lost on every
redeploy unless a persistent disk is attached to that path. No workaround is implemented; attach a
Render persistent disk before relying on uploads in production.

## Codebase agent runtime data (clone cache, vector DB)

The codebase agent's repo clone cache (`REPO_CLONE_ROOT`) and the local vector DB
(`QDRANT_PATH`) also live under that same app-data root, outside the repo tree — deliberately:
a clone cache nested inside a project you then register and ingest would otherwise get ingested
as part of that project's own code (this happened once during development; see
`docs/codebase-agent-handoff.md`). `app/main.py` refuses to start if the resolved clone root ever
ends up inside a registered repo's path, regardless of where these settings point.

On Render, this app-data root is just as ephemeral as the resources directory above:
- The **clone cache** needs no persistent disk — it's rebuilt for free on next use by re-cloning
  the registered URL. Nothing is lost that a re-clone can't reproduce.
- The **vector DB** (Qdrant) losing its embeddings means re-computing them from the durable
  source (Vault entries, chat history — all in the SQL database), not losing user data, but it
  does cost the re-embedding compute/time. Attach a persistent disk to this path if that's
  undesirable in production.

## Free-tier survival notes

- Gemini free ≈ 10 requests/minute. One chat turn = 1 intent call (Groq) + 1 stream (Gemini), so normal usage is fine; hammering Generate buttons isn't.
- Free tiers change without notice — that's why everything goes through `core/llm.py`. Add/replace a provider in one place.
- Don't put real/sensitive data through free tiers; they may train on inputs.
