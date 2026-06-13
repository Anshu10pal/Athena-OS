/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#06080C",
        ink2: "#0A0D14",
        panel: "#0C1119",
        panel2: "#10171F",
        line: "#1E2738",
        fog: "#9AA4B4",
        snow: "#FFFFFF",
        softwhite: "#E6ECF4",
        brass: "#D4B36A",
        brassdim: "#B8954A",
        cyan: "#5FD3E0",
        cyanbright: "#7FE9F0",
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
