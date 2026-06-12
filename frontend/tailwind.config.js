/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B0E14",
        panel: "#11151D",
        panel2: "#161B26",
        line: "#222938",
        fog: "#8A93A6",
        snow: "#E8EBF1",
        brass: "#D4B36A",
        brassdim: "#9C854F",
        sage: "#7FB58C",
        ember: "#D98A6A",
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["Inter", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
