# Drop 1 — Holographic Hub · Spaced Repetition · Achievements · Wake Word

The foundation for your feedback testers: a spectacular first impression plus a sticky core loop.

## Apply
```powershell
# Backend — no new Python packages; migrations run automatically on startup
cd D:\Athena\athena-os\backend
.\venv\Scripts\Activate.ps1
python run.py            # creates achievements + review_items tables, adds columns

# Frontend — ONE new dependency (Three.js)
cd D:\Athena\athena-os\frontend
npm install              # picks up three + @types/three from package.json
npm run dev
```
Hard-refresh the browser (Ctrl+Shift+R).

## 1. Auth that actually persists (fixes your testers getting logged out)
- Token moved from `sessionStorage` (wiped on tab close) to `localStorage` — survives browser restarts.
- Token lifetime extended to 30 days for the feedback phase.
- ACTION on your machine: make sure `backend/.env` has a FIXED `SECRET_KEY` (if it changes between
  restarts, all tokens die) and does NOT pin `ACCESS_TOKEN_EXPIRE_MINUTES=1440`.

## 2. WebGL holographic homepage (Three.js)
- Real WebGL: a 2,600-point depth starfield (brass + cyan, additive blending) and a holographic
  core (three rotating rings + glowing sphere with additive halos), rendered by Three.js.
- DOM glass layer on top: six flanking station cards (no overlap with the center column),
  receding floor grid, mouse-driven 3D scene tilt, depth-scaled parallax.
- Click the orb / your name → chat. Click any panel → that module. Esc → back to hub.
- Graceful fallback: if a tester's browser has no WebGL, the scene simply renders without the
  particle layer rather than crashing.

## 3. Spaced repetition with decay (Review Queue)
- Completing a node's assessment now schedules it for review on an expanding interval
  (1 → 3 → 7 → 21 → 60 days).
- Review Queue page: due count, overall memory strength, and per-topic strength bars that
  visibly decay (green → brass → coral) the longer a review is overdue.
- A review is a 5-question recall quiz drawn from that node's question pool. Pass (≥70%) advances
  the interval and awards XP; fail resets it to 1 day.
- The Hub's Review station shows how many are due today.

## 4. Achievements
- 12 badges across bronze/silver/gold tiers (First Steps, Scholar, Deep Diver, Flawless, Ascendant,
  Luminary, Consistent, Unstoppable, In the Arena, Orator, Silver Tongue, Memory Keeper).
- Unlocks are checked automatically after assessments, speeches, interviews, and level/streak changes.
- Achievements page = a badge wall; locked badges show requirements.

## 5. Wake word ("Hey Athena")
- Settings → Wake Word toggle. When on, ATHENA listens via the browser's speech recognition
  (Chrome/Edge) and opens chat when it hears "Athena". Reload after enabling.
- Off by default; listens only while ATHENA is open in the tab.

## 6. Cyan + white + brass + black theme (all pages)
- Centralized in Tailwind tokens + index.css, so every page shares one palette:
  black depth, white focus, brass = achievement/warmth, cyan = energy/activity.
- Cards are now glassmorphic (backdrop blur + brass hairline); buttons gained brass/cyan glow.

## New API
GET  /api/review/due · POST /api/review/{id}/start · POST /api/review/{id}/submit
GET  /api/achievements
(analytics/dashboard now also returns reviews_due, memory_strength, achievements_unlocked)
