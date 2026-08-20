import { expect, test } from "@playwright/test";
import { authenticate } from "./auth";
import { settle } from "./settle";

// Checkpoint 5's genuine gap. The send path, repeated values and the 300ms
// debounce all shipped in 9fb9bce; what was missing was any signal during the
// window between "the filter changed" and "the graph finished redrawing" --
// measured at 10-11.5s on apache/superset, during which the counter has already
// moved and the picture has not.
//
// The indicator is caught by POLLING rather than by a single sample: it is
// transient by definition, so one screenshot after the fact would find it gone
// and prove nothing. The poll runs from the moment the filter is toggled.
test("a re-layout after a filter change is signalled", async ({ page }) => {
  test.setTimeout(240_000);
  await authenticate(page);
  await page.goto("/repos/6");
  await settle(page);
  await page.getByRole("button", { name: "Architecture", exact: true }).first().click();

  const counter = page.getByText(/Showing [\d,]+ of [\d,]+ files/).first();
  await expect
    .poll(async () => (await counter.innerText()).trim(), { timeout: 90_000, intervals: [500] })
    .toMatch(/Showing 6,523 of/);

  const indicator = page.getByText(/redrawing the graph/);
  expect(await indicator.count(), "indicator must be absent while nothing is refetching")
    .toBe(0);

  await page.getByRole("button", { name: "python", exact: true }).first().click();

  // Seen at all, during the window.
  let sawIt = false;
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (await indicator.count()) { sawIt = true; break; }
    await page.waitForTimeout(150);
  }
  // eslint-disable-next-line no-console
  console.log(`[indicator] appeared during re-layout: ${sawIt}`);
  expect(sawIt, "the re-layout window must be signalled").toBe(true);

  await page.screenshot({ path: "e2e/__artifacts__/refilter-indicator.png" });

  // And it must GO AWAY -- an indicator that never clears is worse than none,
  // because it makes a finished view look permanently busy.
  await expect
    .poll(async () => indicator.count(), { timeout: 120_000, intervals: [500] })
    .toBe(0);
  // eslint-disable-next-line no-console
  console.log("[indicator] cleared after the graph settled");
});
