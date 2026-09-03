# ATHENA OS — Architecture

Detailed system design beyond what fits in the README.

## Layered view

```
PRESENTATION   React + Vite + TS  ─  Tailwind  ─  Framer Motion  ─  Web Audio
─────────────────────────────────────────────────────────────────────────────
APPLICATION    Hub · Chat (SSE) · Roadmap · Interview · Oratory · Missions · Vault
─────────────────────────────────────────────────────────────────────────────
AGENT          Commander → Learning / Research / Memory / General
               LangGraph: Roadmap generate→validate, Sub-map expansion
─────────────────────────────────────────────────────────────────────────────
LLM ROUTER     Gemini Flash (primary, vision) ⟷ Groq Llama 3.3 (fast lane)
               OpenAI SDK · httpx · provider fallback on 429/timeout/SSL
─────────────────────────────────────────────────────────────────────────────
SERVICES       vector_store (Qdrant+FastEmbed) · content_hub (GitHub fetch+cache)
               voice (faster-whisper + Kokoro + Piper) · briefing · analytics
─────────────────────────────────────────────────────────────────────────────
PERSISTENCE    SQLite (relational state) · Qdrant local (vectors) · GitHub (community)
```

## Request flows

### Streaming chat

```
User types       →  POST /api/chat/stream
                    │
                    ▼
            Commander.route(user, msg)
              ├── detect_intent  ─┐  parallel via ThreadPoolExecutor
              └── build_context ─┘  (intent + memory fan-out)
                    │
                    ▼
            chat_stream(messages)
              ├── Try Gemini  (primary, streams tokens)
              └── Fallback to Groq on 429/SSL
                    │
                    ▼
            SSE events to client:
              { type: "meta", intent }
              { type: "token", text }    ← repeated
              { type: "done" }
                    │
                    ▼
            Persist exchange:
              ├── vector_store.add_memory()
              └── VaultEntry insert
```

Time-to-first-token typically 400–1500ms. Visible in the HUD strip live.

### Roadmap generation (LangGraph)

```
POST /api/roadmap/generate
   │
   ▼
StateGraph(RoadmapState):
   ─ generate  (Gemini)  → draft JSON
   ─ validate  (Groq)    → fixed/validated JSON
   ─ END                 → first node "available", rest "locked"
   │
   ▼
Persisted as Roadmap row in SQLite.
```

Sub-roadmap expansion follows the same pattern but parents are linked via `parent_roadmap_id` + `parent_node_id` for breadcrumb navigation and auto-completion bubbling.

### Node assessment

```
Click "Begin assessment" (15/20/25 Qs by node weight)
   │
   ▼
POST .../assessment/start
   ├── Generate questions in batches of 5 (Groq, JSON mode, dedup)
   └── Store with answers server-side (client never sees correct answer index)
   │
   ▼
User picks answers, submits all
   │
   ▼
POST /assessment/{id}/submit
   ├── Grade locally
   ├── If ≥ 70%: node.status = "completed", XP 150-225, unlock dependents
   ├── If parent_roadmap_id and all child nodes done: auto-complete parent (+100 XP)
   └── Return per-question results + weak topics
```

## Data model

### SQLite tables

```
users
  id, email, name, hashed_password
  experience_level, current_role, target_role, learning_goals
  skills (JSON: {"Python": 4, "RAG": 3})
  voice (TTS voice name — a Kokoro voice such as `af_heart`; may still hold a
        legacy Edge-TTS ID like `en-US-AriaNeural` for accounts set before
        Phase 6, which the TTS service degrades to the default rather than
        failing on)
  xp, streak, last_active (YYYY-MM-DD)

roadmaps
  id, user_id, title, target_role
  nodes (JSON: [{id, title, description, skills, status, depends_on, custom?}])
  parent_roadmap_id, parent_node_id   ← recursive linkage

node_content
  id, user_id, roadmap_id, node_id, briefing (JSON-as-text: {definition, eli5, briefing})

assessments
  id, user_id, roadmap_id, node_id
  questions (JSON: [{q, options, answer, topic, given?}])
  status, score

missions
  id, user_id, objective, difficulty, xp_reward, skills_gained, status, date

interview_sessions
  id, user_id, role, jd
  mcq (JSON), mcq_score, transcript (JSON), scores (JSON), status

speech_sessions
  id, user_id, topic, mode, target_secs, transcript, metrics (JSON), scores (JSON)

vault_entries
  id, user_id, kind, title, content, extra (JSON), created_at

resource_cache
  slug, payload (JSON from athena-content), fetched_at   ← 24h TTL
```

Lightweight ALTER TABLE migrations run on startup in `main.py` so schema changes don't require a fresh DB.

### Vector store

- Qdrant in embedded mode (no server process)
- Storage at `./qdrant_data/`
- Collection: `athena_memory`
- Embedding model: `BAAI/bge-small-en-v1.5` via FastEmbed (ONNX, 384-dim)
- Filter on `user_id` for per-account isolation
- Background warmup at FastAPI startup so the first chat doesn't pay the 2-4s model load

## Performance notes

| Optimization | Impact |
|---|---|
| Parallel intent + memory in Commander | ~40% TTFB reduction |
| Embedding warmup at startup | First chat no longer pays 2-4s model load |
| Groq fast-lane for short JSON calls (intent, scoring) | ~6× speed on internal calls |
| Browser TTS fallback | Voice never silently fails |
| MCQ batches of 5 (not 25) | Faster generation, better dedup |
| `httpx.Client(verify=False)` for corporate proxies | Lets LLM router survive SSL interception |

## Threat model (lightweight, single-user local app)

- **JWT in sessionStorage** — fine for local dev, do not deploy this verbatim publicly
- **No multi-tenant data isolation testing** — every query filters by `user_id` but no fuzz-testing
- **`verify=False` on LLM HTTP client** — knowingly weakened TLS for corporate proxy compatibility. Re-enable if deploying.
- **Free LLM tiers may train on inputs** — don't put truly sensitive data in chat
- **Community content moderation** — GitHub PR review is the only check; spam dies in the issue queue
