import { expect, test } from "@playwright/test";

// Proves the harness itself works before anything depends on it: that
// `channel: "chrome"` resolves to the installed browser and a page can be
// driven. Deliberately asserts nothing about this application -- a smoke test
// that also touched the app could fail for two unrelated reasons and would not
// distinguish "Playwright is broken" from "the app is broken", which is the one
// thing it exists to tell us.
test("the browser harness runs", async ({ page }) => {
  await page.goto("about:blank");
  await expect(page).toHaveTitle("");
  expect(page.url()).toBe("about:blank");
});
