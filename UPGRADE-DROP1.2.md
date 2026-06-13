# Drop 1.2 — Geometric core + reference-style Hub & Chat

Frontend-only. Apply:
  cd D:\Athena\athena-os\frontend
  npm install      (no new deps; safe no-op)
  npm run dev
Hard refresh (Ctrl+Shift+R).

## New geometric core (GeoCore)
Replaced the rings+sphere with the reference look: a glowing WIREFRAME ICOSAHEDRON
(two counter-rotating shells) + glowing vertex nodes + a bright energy center with
halos + a vertical light beam + concentric ground "portal" rings that pulse and rotate.
Cyan + violet shell, brass/gold core — matches your references and the app palette.

## Hub — reference layout
- Now lives INSIDE the app shell, so the left sidebar is always present (navigate from there).
- Geometric core centered, welcome + briefing below it, NO floating cards (per your call).
- Click the core to open chat. A "reviews due" pill appears when you have reviews.

## Chat — reference layout
- Geometric core centered as the backdrop, NO cards around it.
- Docked "Ask Athena anything…" input bar at the bottom (mic · mute · text · send),
  glassmorphic with cyan focus glow.
- The core goes TRANSLUCENT once a conversation starts, so messages read clearly over it.
- State label (IDLE / THINKING / SPEAKING) sits top-center, like the reference.

## Wake word — now self-diagnosing
The Hub now tells you the status instead of failing silently:
- "● LISTENING FOR HEY ATHENA" (cyan)  → it's armed; say "Athena"
- "Wake word needs Chrome or Edge"      → unsupported browser
- "Allow the microphone, then reload…"  → permission not granted yet
Still requires: Settings → Wake Word ON, reload, Chrome/Edge, allow mic.
If you see NO wake-word line at all, the toggle is off in Settings.
