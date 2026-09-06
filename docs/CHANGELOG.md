# Changelog

All notable changes per release. Dates are local time of the build.

## v3.3 — Voice, hands-free, editable roadmaps, tailored interviews

- Settings page: voice picker (Indian English Neerja/Prabhat + US/UK/AU), Test voice, change password
- Chat: hands-free mic — auto-stops after 2s silence, transcribes, answers, speaks back
- Roadmap: add custom topics inline, remove irrelevant nodes (dependents auto-rewire), multi-root switcher
- Interview Arena: target a specific job (title + JD) for tailored questions; choose to finish or keep going after Q4 (up to 10)
- Oratory: timestamp stopwatch (drift-immune), filler detection fixed at Whisper layer (`suppress_tokens=[]`), no-repeat topics
- Backend: `users.voice` + `interview_sessions.jd` columns auto-migrated

## v3.2 — Recursive roadmaps, audible Athena, deeper oratory

- Recursive roadmap expansion: graph after graph, Machine Learning → Supervised → K-Means
- Parent auto-completion + 100 XP bonus when sub-map is fully cleared
- Breadcrumb trail navigation between graph levels
- Structured dossiers: WHAT IT IS / ELI5 / BRIEFING / LINKS
- Chat TTS 3-tier fallback: Edge-TTS → Piper → browser speechSynthesis (guaranteed audible)
- Oratory: confidence hedges, weak words, talk ratio, pace-over-time chart
- Full-width layout on all pages (chat keeps a 1100px readable column)
- Sidebar restyled with gradient, mini orb, icons, brass rail, level bar, constellation decoration

## v3.1 — First post-flight patch

- Hub stations form a true orbital ring (CSS override bug fixed, trigonometric placement)
- Interview: voice answers in the descriptive stage, full MCQ review + transcript on scorecard
- Missions: rotation top-up to 3 active
- Oratory: exact filler counts, grammarian corrections, vocabulary upgrades
- Chat: voice in → voice out automatically

## v3.0 — Command Hub, gated learning, Oratory Deck

- New post-login Command Hub at `/`
- Roadmap node dossiers + 15/20/25-Q gated MCQ assessments
- Two-stage Interview Arena (10 MCQs + 4 descriptive)
- Oratory Deck (Toastmasters-style)
- Mission rotation
- Sci-fi styling pass: corner brackets, decrypt text, animated numbers, status strip, arc gauges
- Backend speed: parallel commander, embedding warmup
- GitHub-backed community content layer

## v2 — "Jarvis layer"

- Particle field background (state-reactive)
- Boot sequence
- Audio-reactive VoiceOrb (Web Audio AnalyserNode)
- HUD telemetry strip (state, agent, TTFB, tok/s)
- Ctrl+K command palette
- Constellation roadmap (self-drawing dependency lines)
- Level-up overlay
- Daily AI-generated briefing
- Sound design (Web Audio oscillators, mute toggle)
- Daily briefing endpoint baked in

## v1 — Foundation

- JWT auth + streak tracking
- Commander agent (intent → routing)
- SSE streaming chat with vector memory
- Embedded Qdrant + FastEmbed
- LangGraph roadmap engine (generate → validate)
- 6-question Interview Arena
- Presentation Arena (.pptx/.pdf upload)
- Knowledge Vault + semantic search
- LLM-generated daily missions
- Analytics dashboard + Digital Twin
