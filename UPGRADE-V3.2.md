# v3.2 — Recursive roadmaps, audible Athena, deeper oratory, full-width UI

Apply: extract over your folder, restart backend (auto-migrates two new roadmap columns),
restart frontend dev server, hard refresh (Ctrl+Shift+R).

## Recursive roadmap — graph after graph
- Every node dossier now has "EXPAND INTO SUB-MAP": generates a granular sub-roadmap
  (Machine Learning -> Supervised/Unsupervised/RL -> later expand those into K-Means,
  XGBoost, SVM, LSTM... all the way to leaf techniques). Each sub-node is a full node:
  own dossier, own assessment, own XP.
- Breadcrumb trail above the constellation navigates between graph levels.
- Clear every node in a sub-map -> the parent node AUTO-COMPLETES (+100 bonus XP)
  and unlocks its dependents. Already-expanded nodes show "OPEN SUB-MAP" instead.

## Dossier content upgraded
Every node now generates three layers: WHAT IT IS (exact technical meaning),
ELI5 (everyday analogy, highlighted box), and the full BRIEFING — followed by links.
(Old cached briefings still display; new/expanded nodes get the full structure.)

## Chat voice — guaranteed audible
Three-tier TTS: Edge-TTS neural voice -> Piper -> the browser's built-in speech engine.
If the server path fails (proxy, missing install, autoplay block) Athena now speaks
through the browser instead of failing silently. Voice can no longer be "missing".

## Oratory — deeper analysis
New measured metrics: CONFIDENCE HEDGES ("i think" x4, "maybe" x2 — sounding less sure
than you are), vague-word counts (very/really/thing/stuff), talk ratio, and a
PACE-OVER-TIME chart (WPM per 10s with the 110-150 sweet-spot band shaded).
Plus the v3.1 exact filler counts, grammar corrections, and vocabulary upgrades.

## UI
- All pages now use the full window width (chat keeps a readable 1100px column).
- Sidebar restyled: gradient panel, mini spinning orb in the logo, icons per item,
  brass rail on the active item, faint constellation decoration, and a level
  progress bar under your name.
