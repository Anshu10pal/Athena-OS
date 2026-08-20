import { Page, expect, test } from "@playwright/test";
import { authenticate } from "./auth";
import { settle } from "./settle";

// Checkpoint 4 item 3. `shownFileCount` (RepoDetail.tsx) selects a source per
// view; Focus is not in any branch, so it falls through to
// `visibleGraphNodes.length` -- the array the /graph endpoint CAPS at 400. On
// apache/superset the bar therefore reads "Showing 400 of 6,523 files" on Focus
// regardless of filter, which is the residue of a bug already fixed for the
// other views (see RepoDetail.tsx:764-775).
//
// The bar stays visible on Focus because filter state PERSISTS across view
// changes (RepoDetail's `filters` useState is never reset on view change and is
// synced to the URL at :571-587), so removing the bar would strand a set filter
// with no way to see or clear it.
const ARTIFACT = process.env.FOCUS_ARTIFACT ?? "unnamed";

async function counterOn(page: Page, label: string) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  // Wait for a CONDITION, not a duration. A fixed sleep samples the counter
  // while /graph is still in flight, when it reads "Showing 0 of N" from an
  // empty array -- checkpoint 2.6 spent an investigation on exactly that
  // mistake in a different probe.
  const bar = page.getByText(/Showing [\d,]+ of [\d,]+ files/).first();
  await expect
    .poll(async () => (await bar.innerText()).trim(), { timeout: 60_000, intervals: [500] })
    .not.toMatch(/Showing 0 of/);
  await page.waitForTimeout(2000);
  const visible = await bar.count();
  const text = visible ? (await bar.innerText()).trim() : null;
  // eslint-disable-next-line no-console
  console.log(`[focus] ${label}: counter=${JSON.stringify(text)}`);
  return text;
}

test("Focus counter reports the file set, not the capped array", async ({ page }) => {
  test.setTimeout(240_000);
  await authenticate(page);
  await page.goto("/repos/6");
  await settle(page);

  // Dependency Graph FIRST: it is the positive control, and visiting it also
  // guarantees the /graph response has arrived before Focus is sampled, so a
  // cold-load transient cannot be mistaken for the defect.
  const depgraph = await counterOn(page, "Dependency Graph");
  const focus = await counterOn(page, "Focus");

  await page.getByText(/Showing [\d,]+ of [\d,]+ files/).first()
    .screenshot({ path: `e2e/__artifacts__/focus-${ARTIFACT}.png` });

  // DISCRIMINATION (§17.30): the probe must be able to read a counter and see
  // it differ between views. If both read identically here, the probe cannot
  // perceive what this test exists to check, whichever way the code behaves.
  expect(depgraph, "positive control: Dependency Graph must report the file set")
    .toMatch(/Showing 6,523 of 6,523 files/);
  // eslint-disable-next-line no-console
  console.log(`[focus] DISCRIMINATION: depgraph=${JSON.stringify(depgraph)} focus=${JSON.stringify(focus)} ` +
    `differ=${depgraph !== focus}`);
});
