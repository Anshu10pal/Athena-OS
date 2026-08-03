/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Values must stay in sync with docs/athena-homepage-wireframe.html's :root block.
        ink: "#070B0A",
        ink2: "#0B1110",
        panel: "#101614",
        panel2: "#161D1A",
        // Function form so Tailwind's opacity modifier (e.g. text-fog/60) actually
        // overrides the alpha channel instead of silently ignoring it — a plain
        // "rgba(...)" string can't be re-modulated by Tailwind's opacity utilities.
        line: ({ opacityValue }) => `rgba(255, 255, 255, ${opacityValue ?? 0.09})`,
        fog: ({ opacityValue }) => `rgba(233, 241, 238, ${opacityValue ?? 0.62})`,
        snow: "#E9F1EE",
        softwhite: "#E9F1EE",
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
