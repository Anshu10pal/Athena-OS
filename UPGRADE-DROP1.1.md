# Drop 1.1 — Hub polish patch

Fixes the four issues from first flight. Frontend-only — no backend changes.

Apply:
  cd D:\Athena\athena-os\frontend
  npm install        (three is already installed; this is a no-op if so)
  npm run dev
Hard refresh (Ctrl+Shift+R).

FIXED
1. Text no longer overlaps the orb — the WebGL core is lifted up and the welcome
   text + briefing now sit cleanly below it. Cards reframed around the higher orb.
2. Clicking the orb opens chat — added a real invisible circular hit-area over the
   core (the core is pure WebGL and had no DOM click target before).
3. Calmer, less cluttered — particle count 2600 -> 1400, dimmer (opacity 0.55),
   smaller core and halos, wider spread. The starfield recedes instead of crowding.
4. "Hey Athena" made robust — the hook now reports when it's actively listening
   (a "● LISTENING FOR HEY ATHENA" line appears under the briefing when active),
   handles mic-permission denial gracefully, and auto-restarts.

WAKE WORD CHECKLIST (it needs all of these):
  - Settings -> Wake Word toggle ON
  - Reload the page after enabling
  - Use Chrome or Edge (Firefox/Safari don't support webkitSpeechRecognition)
  - Allow the microphone permission prompt when it appears
  - You should then see the cyan "LISTENING" line on the hub. Say "Athena".
