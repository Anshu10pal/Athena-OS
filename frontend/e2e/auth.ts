import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Page } from "@playwright/test";

// The package is ESM ("type": "module"), so `__dirname` does not exist here.
const HERE = path.dirname(fileURLToPath(import.meta.url));

// The app stores its JWT in localStorage under "athena_token" (lib/api.ts:1).
// The token is minted out-of-band into e2e/.token (gitignored) rather than
// checked in or driven through the login form: logging in through the UI would
// make every graph test also a test of the auth screen, so a login regression
// would fail tests about layout cancellation and read as a graph bug.
const TOKEN_PATH = path.join(HERE, ".token");

export function readToken(): string {
  if (!fs.existsSync(TOKEN_PATH)) {
    throw new Error(
      `No e2e/.token. Mint one against the running backend before these tests:\n` +
      `  backend/venv/Scripts/python.exe -c "<jwt for a real user>" > frontend/e2e/.token`,
    );
  }
  return fs.readFileSync(TOKEN_PATH, "utf-8").trim();
}

/** Seed auth BEFORE any app script runs, so the app never observes a logged-out
 *  state and never redirects to /login mid-navigation. */
export async function authenticate(page: Page): Promise<void> {
  const token = readToken();
  await page.addInitScript((t) => {
    window.localStorage.setItem("athena_token", t as string);
  }, token);
}
