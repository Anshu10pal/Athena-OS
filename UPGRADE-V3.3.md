# v3.3 — Voice settings, hands-free mic, editable roadmaps, tailored interviews

Apply: extract over folder, restart backend (migrates users.voice + interview jd columns),
restart frontend, hard refresh.

## Settings page (new — sidebar + Ctrl+K)
- ATHENA'S VOICE: pick one neural voice used EVERYWHERE (includes Indian English —
  Neerja & Prabhat — plus US/UK/AU options) with a "Test voice" button.
  Root cause of the male/female switching: the first reply fell back to the browser's
  default voice before Edge-TTS warmed up. One saved voice now rules all replies.
- CHANGE PASSWORD (verifies current password)
- Profile: target role + experience level (drives roadmaps, missions, interviews)

## Chat — hands-free
Mic now AUTO-STOPS after a 2-second pause once you've spoken. Click once, talk,
pause — Athena transcribes, answers, and speaks back. The button still works as a
manual cancel.

## Roadmap — yours to shape (and always saved)
- Roadmaps were already persisted per account; now they're editable:
- ADD any topic: type in the "Add a topic" box -> Athena fills description + skills,
  node appears unlocked, tagged CUSTOM.
- REMOVE any node from the dossier ("not relevant to me") — dependents re-wire and
  unlock automatically.
- Multiple root roadmaps: switcher chips appear when you have more than one.

## Oratory Deck
- Timer rebuilt as a TIMESTAMP STOPWATCH (think + speak) — counts true seconds,
  immune to the interval double-fire that made it skip.
- Filler detection fixed at the Whisper level: suppress_tokens=[] stops Whisper from
  silently deleting your "um"/"uh" before we can count them. The EXACT-COUNTS section
  now always renders (shows "clean run" when zero).
- Topics no longer repeat: your last 12 topics are sent as an avoid-list.

## Interview Arena
- Target a SPECIFIC JOB: enter a title, paste a JD, or both — every MCQ and
  descriptive question is tailored to it.
- After the standard 4 descriptive questions: choose "Submit & get scorecard" or
  "Keep going" (extended round, up to 10).
