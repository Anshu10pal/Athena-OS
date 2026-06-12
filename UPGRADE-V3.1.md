# v3.1 patch — bug fixes from first live flight

Extract over your folder (overwrite all). Restart backend + frontend dev server.
One new optional package for premium voice replies: pip install edge-tts

FIXED
1. Hub stations now form a true orbital ring around the orb (root cause: a CSS
   position override from the v3 styling pass — stations use trigonometric
   placement now, correct at any screen size)
2. Interview descriptive stage: answer BY VOICE — mic button records, transcribes
   via faster-whisper, drops the text into your answer (spoken answers feed the
   communication score through the transcript)
3. Interview scorecard: full review — every MCQ with your pick vs the correct
   answer, plus the complete deep-dive Q&A transcript
4. Missions: top-up logic — active directives always refill to 3
5. Oratory: exact filler words with counts ("um" x7, "you know" x3...),
   plus GRAMMARIAN corrections (your sentence -> fixed) and VOCABULARY upgrades
6. Chat: voice in -> voice out — answering by mic makes Athena speak her reply
   (Edge-TTS neural voice; Piper fallback), no toggle needed. Chats were already
   being saved to vault + memory in the background — confirmed working.

ROADMAP LINKS
Search-style links are the hallucination-proof fallback. The real fix is your
curated bank: upload the Excel (~100 topics with direct links) in chat — it gets
converted to resources/*.json for the athena-content repo, and community links
always render above the fallbacks.
