/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Values must stay in sync with docs/athena-homepage-wireframe.html's :root block.
        // Phase K1 readability pass: `ink` was #070B0A (near-absolute black)
        // against a #E9F1EE foreground — roughly 18:1, which reads as harsh
        // and glaring over long sessions of dense monospace tables. Both ends
        // are pulled in slightly: the background lifts off pure black, the
        // foreground steps back from pure white. Still comfortably past
        // WCAG AA for body text; the point is to reduce glare, not contrast
        // to the edge of legibility.
        ink: "#0A0F0E",
        ink2: "#0D1413",
        panel: "#121917",
        panel2: "#18201D",
        // The `<alpha-value>` placeholder is Tailwind's supported way to keep
        // opacity modifiers working (text-fog/60 etc.) — the previous
        // `({ opacityValue }) => rgba(..., ${opacityValue ?? 0.09})` form did
        // NOT do what its comment claimed. Tailwind always passes
        // `var(--tw-*-opacity)` for the bare utility rather than `undefined`,
        // so the `?? 0.09` fallback never fired and the default alpha was
        // silently 1. Measured in the live app, not inferred:
        //   .text-fog   -> rgb(233,241,238)  (identical to .text-snow)
        //   .border-line-> rgb(255,255,255)  (solid white, not 9%)
        // So every bare `text-fog` rendered at full brightness — the whole
        // dimmed-secondary-text intent was dead app-wide, and bare
        // `border-line` drew solid white rules. That is the actual reason the
        // UI read as harsh, so it is fixed at the source here rather than
        // compensated for with darker hexes.
        //
        // A plain rgba() string gives BOTH the intended default alpha and
        // working modifiers -- verified against the built CSS, which is also
        // what disproved the old comment's premise that it couldn't:
        //   .text-fog     -> #e2ebe899  (alpha 0.60, the default)
        //   .text-fog/70  -> #e2ebe8b3  (modifier still applied)
        //   .border-line  -> #ffffff17  (alpha 0.09)
        line: "rgba(255, 255, 255, 0.09)",
        fog: "rgba(226, 235, 232, 0.60)",
        snow: "#DEE7E4",
        softwhite: "#DEE7E4",
        // Phase K1: `bg-glass` / `bg-glass-2` were already used in 17 places
        // across ArchitectureMap, MatrixView, FileSearch and RepoDetail —
        // and generated NOTHING, because --glass/--glass-2 are CSS custom
        // properties that were never registered as Tailwind colors. Every
        // one of those hover states was silently dead. Same bug class as the
        // `bg-void` incident this project has now hit four times; registering
        // them here fixes all 17 usages at once rather than one at a time.
        glass: "rgba(255, 255, 255, 0.045)",
        "glass-2": "rgba(255, 255, 255, 0.07)",
        accent: "#3DDC97",
        accentdim: "#2FBE82",
        info: "#4FC7D4",
        warning: "#E0B450",
        danger: "#E2646E",
      },
      fontFamily: {
        display: ["'Instrument Sans'", "sans-serif"],
        body: ["'Instrument Sans'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
