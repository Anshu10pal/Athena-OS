import { defineConfig } from "@playwright/test";

// Browser verification for the codebase-agent views.
//
// `channel: "chrome"` drives the Chrome already installed on this machine
// rather than downloading Playwright's own build. That is not a convenience:
// `npx playwright install` pulls ~150MB per browser, and the installed Chrome
// at C:\Program Files\Google\Chrome\Application\chrome.exe is the same engine
// these views are used in. Measured install cost with this setting: 17.7 MB,
// 5.8s -- the package only.
//
// No `webServer` block: the dev servers are long-running and started outside
// the test run (backend :8000, frontend :5173). Having Playwright own their
// lifecycle would make every run pay a cold Vite start, and would race the
// backend's own "port already bound" tripwire against a server a human left
// running -- a documented, previously-hit failure mode in this project.
export default defineConfig({
  testDir: "./e2e",
  // One worker: these tests drive a shared backend and a shared SQLite file.
  // Parallel workers would contend on the same repo rows, and this session has
  // already recorded what unexplained contention costs to diagnose.
  workers: 1,
  // Superset is 6,523 files and the views fetch ~4MB on landing; the default
  // 30s expects a much smaller app.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  use: {
    channel: "chrome",
    baseURL: "http://localhost:5173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
