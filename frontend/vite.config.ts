/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
    // vitest owns src/**/*.test.ts; Playwright owns e2e/**/*.spec.ts. Without
    // this, vitest collects the Playwright specs, fails to resolve
    // `@playwright/test`'s runner, and reports failing FILES while every unit
    // test still passes -- a red suite that says nothing about the code.
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
  },
});
