<div align="center">

# 🦉 ATHENA OS

### Adaptive Intelligence Research Terminal

*A local-first, voice-enabled, multi-agent AI Learning & Career Development Platform*

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.3-1C3C3C?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-D4B36A?style=flat-square)](LICENSE)

[Features](#features) · [Quick Start](#quick-start) · [Architecture](#architecture) · [API](#api-reference) · [Roadmap](#what-comes-next)

</div>

---

## What is ATHENA OS?

ATHENA OS is your personal AI academy. It combines six learning surfaces into one cohesive system:

| Surface | What it does |
|---|---|
| 🌐 **Command Hub** | Sci-fi launcher: central orb speaks your daily briefing; six module stations orbit it with live stats |
| 💬 **Athena Chat** | Voice-first multi-agent conversation — hands-free push-to-talk, neural TTS replies, persistent memory across sessions |
| 🗺️ **Roadmap Engine** | Recursive learning paths (Machine Learning → Supervised → K-Means → ...). Every node has a dossier, MCQ-gated completion, and community-curated study links |
| 🎯 **Daily Missions** | LLM-generated learning directives with XP. Complete one, a new directive deploys in its place |
| 🎙️ **Interview Arena** | Two-stage interviews (10 MCQs + 4-10 descriptive) tailored to any job description |
| 🗣️ **Oratory Deck** | Toastmasters-style impromptu speaking with verbatim filler-counting, grammar correction, and pace analytics |
| 📊 **Presentation Arena** | Upload .pptx/.pdf → slide-by-slide analysis, speaker notes, executive summary |
| 🧠 **Knowledge Vault** | Semantic search over everything you've learned, done, and discussed |

**The differentiator:** ATHENA runs locally on your machine, costs **$0/month** to operate (free Gemini + Groq LLM tiers, no credit card required), and remembers every interaction across sessions through embedded vector memory.

---

## Features

### 🌐 Command Hub — Your Bridge

- Central orb (audio-reactive, click to chat)
- Daily AI-generated briefing typed beneath the orb
- 5 arc gauges for the Digital Twin (technical depth, communication, presentation, AI knowledge, consistency)
- 6 module stations orbiting on a true ring, each showing one live stat
- `Ctrl+K` command palette · `Esc` returns from anywhere

### 🤖 Multi-Agent Pipeline (LangGraph)

- **Commander** routes intent (learn/interview/presentation/research/memory/general)
- **Learning Agent** explains topics personalized to your level + retrieved memory
- **Research Agent** structured reports with comparisons
- **Memory Agent** answers from your vector store
- **Roadmap Engine** runs generate → validate → repair as a real LangGraph workflow
- **Interview Agent** adapts follow-ups; **Scorer** rates on 5 dimensions
- **Presentation Agent** decomposes decks into storytelling/business-impact/depth
- **Briefing Agent** writes personalized morning greetings
- **Oratory Evaluator** grades structure/relevance/vocabulary/delivery

### 🗺️ Recursive Roadmaps

- Generate a roadmap for any target role (LangGraph: generate → validate)
- Each node has: dossier (definition + ELI5 + briefing), community study links, generated search links, MCQ-gated assessment
- **Expand any node into a granular sub-roadmap** — Machine Learning → Supervised → K-Means, recursively
- Add custom topics · remove irrelevant ones (dependents auto-rewire)
- Clear a sub-map → parent node auto-completes with +100 XP bonus
- Locked/Available/In-Progress/Completed/Skipped node states with dependency unlocking

### 🎙️ Voice Stack

- **STT**: `faster-whisper` (local, CPU int8, ~80MB)
- **TTS** (3-tier fallback chain):
  1. Edge-TTS — free Microsoft neural voices (Neerja, Aria, Guy, Jenny, Sonia, Natasha, Prabhat)
  2. Piper — fully local fallback
  3. Browser `speechSynthesis` — guaranteed audible last resort
- **Hands-free chat**: click mic, talk, pause 2s → auto-transcribes, answers, speaks back

### 🗣️ Oratory Deck — Toastmasters in code

- Topic draw modes: classic / professional / wildcard (no-repeat: avoids your last 12)
- 30s think timer → 1/2/3 min speak phase (timestamp stopwatch, drift-immune)
- Green/amber/red timing-card border like real Toastmasters
- **Measured metrics** (from word timestamps):
  - Exact filler counts per word (`"um" ×7`, `"you know" ×3`) — uses `suppress_tokens=[]` so Whisper doesn't silently delete fillers
  - Confidence hedges (`"i think"`, `"maybe"`)
  - Vague words (`very`, `really`, `thing`)
  - WPM with sweet-spot band (110-150)
  - Pause analysis (rhetorical vs stall)
  - Talk ratio · longest pause · pace over time
- **AI-evaluated**: structure / relevance / vocabulary / delivery scores
- **Grammarian section**: your sentence → corrected version
- **Vocabulary upgrades**: weak word → stronger alternative
- XP rewards improvement over your own last session, not absolute score

### 🎯 Interview Arena

- 6 quick tracks (AI Engineer, ML Engineer, Data Scientist, Architect, PM, Behavioral)
- **OR** target a specific job: enter title + paste JD → every question tailored
- Stage 1: 10 MCQs, 30s each, auto-advance on timeout
- Stage 2: 4 adaptive descriptive questions
- **Continue or finish** after Q4 — extended round up to 10
- Voice answers (mic → transcription → answer)
- Final scorecard blends measured MCQ accuracy into technical score; full review of every MCQ + transcript

### 💾 Persistent Memory

- **Short-term**: SQLite (users, roadmaps, sessions, vault entries)
- **Vector**: embedded Qdrant + FastEmbed (ONNX, CPU-only, no Docker, no torch)
- **Long-term context**: every chat, interview, presentation, and speech feeds the vector store
- **Semantic vault search**: "what did I learn about LangGraph?"

### 🌐 Community Content Layer (GitHub-backed)

- Resources live in a public `athena-content` GitHub repo as JSON files (one per topic)
- Every install fetches from `raw.githubusercontent.com`, caches 24h in SQLite
- **Suggest a resource** button opens a pre-filled GitHub issue (no API tokens, no credentials)
- Maintainer reviews & merges → next 24h all users see the new link
- Modeled on roadmap.sh's contribution flow with link-type taxonomy: `official`, `article`, `video`, `course`, `opensource`

### 🎨 Sci-Fi UI

- Astrolabe Voice Orb (4 states with audio reactivity)
- Plexus particle field background (reacts to Athena's state)
- Boot sequence with typed title + systems check
- Constellation roadmap with self-drawing dependency lines
- Decryption text effect on headings
- Animated number counters (XP, scores)
- Arc gauges, corner brackets on cards, scanline mounts
- Level-up overlay with brass ring burst
- Sound design (Web Audio oscillators — chime, unlock, fanfare, ambient hum)
- Brass-on-graphite palette (`#D4B36A` on `#0B0E14`) — premium not gaming

---

## Quick Start

### Prerequisites

| Need | Version | Why |
|---|---|---|
| Python | 3.12 (3.13 has C-extension issues with `mmh3`) | Backend runtime |
| Node.js | 20 LTS or 22 LTS | Frontend build |
| Git | any | Version control |
| 16 GB RAM | — | No GPU needed (CPU-only inference for embeddings and Whisper) |
| Free API keys | Gemini + Groq | No credit card required |

### Get your free LLM keys (2 minutes)

1. **Gemini** (primary, vision-capable): https://aistudio.google.com → "Get API key" → Create
2. **Groq** (fast lane, fallback): https://console.groq.com/keys → Create API key

### Backend

```powershell
cd D:\Athena\athena-os\backend

# Use Python 3.12 explicitly (works around prebuilt-wheel gaps in 3.13)
& "C:\Program Files\Python312\python.exe" -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Configure
Copy-Item .env.example .env
notepad .env                 # paste GEMINI_API_KEY, GROQ_API_KEY, SECRET_KEY

# Launch
python run.py
```

Backend runs at **http://127.0.0.1:8000**. Interactive docs at `/docs`.

### Frontend

```powershell
cd D:\Athena\athena-os\frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Register, watch the boot sequence, you're in.

### Voice (optional — Phase 4)

```powershell
cd backend
pip install faster-whisper edge-tts
```

- **Whisper "base" model** auto-downloads on first mic use (~80MB)
- **Edge-TTS** uses Microsoft's free neural voices over a websocket. **Behind corporate proxies** that intercept SSL, you may need to patch the aiohttp connector — see [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- If both fail, the browser's built-in `speechSynthesis` engages automatically

### Community Content Repo (one-time setup)

Create a public GitHub repo named **`athena-content`** under your account. Seed it from `docs/athena-content-seed/`. Update `CONTENT_REPO` in `backend/app/services/content_hub.py` to point at your username. Push, and every dossier in ATHENA starts pulling community links from your repo.

---

## Architecture

### Stack at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│                     React 18 + TypeScript + Vite                │
│       Framer Motion · Tailwind · Lucide · Web Audio API         │
│                                                                  │
│   Hub  Chat  Roadmap  Missions  Interview  Oratory  Vault       │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP + SSE
┌────────────────────────────▼────────────────────────────────────┐
│                       FastAPI + LangGraph                        │
│                                                                  │
│   Commander Agent ──┬── Learning   ── Briefing                  │
│                     ├── Research   ── Mission Generator         │
│                     ├── Memory     ── Oratory Evaluator         │
│                     ├── Interview  ── Roadmap Engine (graph)    │
│                     └── Presentation                            │
│                                                                  │
│   LLM Router: Gemini Flash (primary) ⟷ Groq Llama 3.3 (fast)    │
└──┬───────────────┬───────────────┬─────────────┬────────────────┘
   │               │               │             │
   ▼               ▼               ▼             ▼
 SQLite        Qdrant           GitHub        faster-whisper
(persistent)   (embedded,      (athena-      + Edge-TTS
              FastEmbed ONNX)   content)     (voice)
```

### Repository layout

```
athena-os/
├── backend/
│   ├── app/
│   │   ├── agents/          # commander, prompts, roadmap LangGraph workflow
│   │   ├── api/             # auth, chat, roadmap, interview, oratory, missions, vault, voice, briefing, analytics
│   │   ├── core/            # config, security (JWT), llm router with provider fallback
│   │   ├── db/              # SQLAlchemy models, session, schemas
│   │   ├── services/        # vector_store, content_hub (GitHub sync)
│   │   └── main.py          # FastAPI app, migrations, embedding warmup
│   ├── requirements.txt
│   ├── requirements-voice.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/      # VoiceOrb, ParticleField, BootSequence, NodeDossier, AssessmentRunner, CommandPalette, etc.
│   │   ├── pages/           # Hub, Chat, Roadmap, Missions, InterviewArena, OratoryDeck, PresentationArena, Vault, Settings
│   │   ├── lib/             # api client, sound engine, fx (decrypt + animated numbers), audio-reactive hook
│   │   └── store/           # auth + orb React contexts
│   ├── package.json
│   └── vite.config.ts
├── docs/                    # detailed guides (architecture, API, troubleshooting, deployment)
└── athena_console.py        # Streamlit fallback console (no Node required)
```

### Key design choices

| Decision | Why |
|---|---|
| **Two LLM providers via OpenAI SDK** | Both Gemini and Groq expose OpenAI-compatible endpoints. One client, two base URLs, automatic fallback on 429/timeout/SSL. |
| **Embedded Qdrant + FastEmbed** | No Docker, no separate vector server, no `torch` dependency. CPU-only ONNX runtime fits your no-GPU machine. |
| **LangGraph for multi-step flows only** | Single-turn chat uses simple routing for speed. Roadmap generation uses a real graph (generate → validate). |
| **SQLite for everything else** | Zero ops. Single file. `athena.db` is your entire user state. |
| **GitHub for community content** | Free, version-controlled, moderation via PR review, zero credentials in the client. |
| **Hallucination-proof fallback links** | Generated links use search URLs (GfG/YouTube/DuckDuckGo) — they can never 404. |
| **Whisper `suppress_tokens=[]`** | Disables Whisper's silent filler-removal so we can actually count "um"s. |
| **Timestamp stopwatches** | All timers compute elapsed time from `Date.now()`, immune to interval drift. |

For deeper architecture detail, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## API Reference

Full interactive docs are at **http://127.0.0.1:8000/docs** when the backend is running.

Highlight summary in [`docs/API.md`](docs/API.md). Key endpoints:

```
POST  /api/auth/register              JWT-issuing registration
POST  /api/auth/login                 OAuth2-form login
POST  /api/auth/change-password
PATCH /api/profile                    update target role, voice, etc.

POST  /api/chat/stream                SSE streaming chat with intent + memory
GET   /api/briefing                   personalized daily briefing

POST  /api/roadmap/generate           LangGraph-driven roadmap creation
GET   /api/roadmap                    list user's roadmaps with nodes
POST  /api/roadmap/{id}/node          add custom topic
DELETE /api/roadmap/{id}/node/{nid}   remove topic
GET   /api/roadmap/{id}/node/{nid}/dossier
POST  /api/roadmap/{id}/node/{nid}/expand          generate granular sub-roadmap
POST  /api/roadmap/{id}/node/{nid}/assessment/start
POST  /api/roadmap/assessment/{aid}/submit

POST  /api/interview/start            10 MCQs, optionally JD-tailored
POST  /api/interview/mcq              submit MCQ batch → opens descriptive stage
POST  /api/interview/answer           descriptive answer (optional finish=true)

POST  /api/oratory/topic              generate topic (no-repeat over last 12)
POST  /api/oratory/analyze            audio + topic → metrics + AI scores
GET   /api/oratory/history            filler-rate trend

GET   /api/missions/today             3 active directives (top-up)
POST  /api/missions/{id}/complete     completes + deploys replacement

POST  /api/presentation/analyze       .pptx/.pdf → structured deck review

POST  /api/vault/notes                save a note
GET   /api/vault/entries
GET   /api/vault/search?q=...         semantic search

POST  /api/voice/transcribe           audio → text (Whisper)
POST  /api/voice/speak                text → audio (Edge-TTS → Piper fallback)

GET   /api/analytics/dashboard        XP, level, streak, twin, station stats
```

---

## Configuration

### `backend/.env`

```bash
# Both free, no credit card
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key

# Auth
SECRET_KEY=any_long_random_string
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Storage (relative paths fine)
DATABASE_URL=sqlite:///./athena.db
QDRANT_PATH=./qdrant_data
```

### Voice catalog

Edit the `VOICES` array in `frontend/src/pages/Settings.tsx`. Any [Edge-TTS voice ID](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support) works.

### Community content repo

In `backend/app/services/content_hub.py`:
```python
CONTENT_REPO = "Anshu10pal/athena-content"   # ← your GitHub repo
CACHE_TTL_HOURS = 24
```

---

## Troubleshooting

Common issues and their fixes are catalogued in [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md), including:

- Python 3.13 `mmh3` wheel build failure → use 3.12
- Corporate proxy SSL errors (OpenAI client, Edge-TTS websocket, Whisper model download)
- `npm install` PATH issues on Windows
- Edge-TTS 501 → 3-tier voice fallback engages automatically
- Boot sequence crash, mission rotation, Whisper filler suppression

---

## What comes next

Logged in [`docs/CHANGELOG.md`](docs/CHANGELOG.md) and the roadmap below.

**Phase 4 — Spaced Repetition & Decay**
Review queue, knowledge decay tracking on the Digital Twin, scheduled MCQ recall

**Phase 5 — Boardroom Simulator**
Upload deck → face animated personas (CEO/CTO/CFO/Customer) taking turns grilling you

**Phase 6 — Resume Lab**
Upload resume → scored against target role + interview questions generated from your own bullets

**Phase 7 — Knowledge Graph View**
Vault as an explorable constellation, semantic similarity as visual edges

**Phase 8 — Mobile Companion**
React Native shell hitting the same FastAPI backend

---

## Credits

- Inspired by [roadmap.sh](https://roadmap.sh)'s content model and node taxonomy
- LLM tier: [Google Gemini](https://aistudio.google.com) (free) + [Groq](https://groq.com) (free)
- TTS: [Microsoft Edge-TTS](https://github.com/rany2/edge-tts) (free neural voices)
- STT: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Vector store: [Qdrant](https://qdrant.tech) + [FastEmbed](https://github.com/qdrant/fastembed)
- Multi-agent orchestration: [LangGraph](https://langchain-ai.github.io/langgraph/)

Built by [Anshuman Pal](https://github.com/Anshu10pal) · AFDE Jan 2026 batch · Prodapt

## License

MIT — see [LICENSE](LICENSE).
