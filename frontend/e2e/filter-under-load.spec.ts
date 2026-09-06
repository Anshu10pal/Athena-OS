import { Page, expect, test } from "@playwright/test";
import { authenticate } from "./auth";
import { settle } from "./settle";

// Checkpoint 6: does the file filter actually reduce the graph on the surfaces
// that render it, on the repo where the cap and the latency both bite?
//
// Every observation here carries its own discrimination proof, because this
// session produced five instrument failures and two of them were counter reads.
// The pattern used throughout: capture UNFILTERED, apply the filter, capture
// FILTERED, and assert they DIFFER in the expected direction. A probe that
// reports the same value either way has not perceived the filter, and its
// "verdict" would be meaningless whichever way the product behaved.

async function counterText(page: Page): Promise<string> {
  const bar = page.getByText(/Showing [\d,]+ of [\d,]+ files/).first();
  // Condition, not duration: a fixed sleep samples while /graph is in flight,
  // when the counter reads "Showing 0 of N" from an empty array.
  await expect
    .poll(async () => (await bar.innerText()).trim(), { timeout: 90_000, intervals: [500] })
    .not.toMatch(/Showing 0 of/);
  return (await bar.innerText()).trim();
}

function parseShown(t: string): number {
  return Number((t.match(/Showing ([\d,]+) of/)?.[1] ?? "0").replace(/,/g, ""));
}

/** The counter once it has STOPPED MOVING.
 *
 *  Not "once it is non-zero": this view's counter passes through two transient
 *  values on the way to its real one -- 0 while /graph is in flight, then 400
 *  from the capped fallback while dirGraph is still loading. Sampling at either
 *  produces a confident wrong number, which is exactly how the first run of
 *  this spec "measured" a filter increasing the file count from 400 to 6,523. */
async function stableCount(page: Page, timeoutMs = 120_000): Promise<number> {
  const bar = page.getByText(/Showing [\d,]+ of [\d,]+ files/).first();
  const deadline = Date.now() + timeoutMs;
  let last = -1;
  let sameSince = 0;
  while (Date.now() < deadline) {
    const v = parseShown((await bar.innerText()).trim());
    if (v === last && v > 0) {
      if (!sameSince) sameSince = Date.now();
      if (Date.now() - sameSince > 3000) return v;
    } else {
      sameSince = 0;
      last = v;
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`counter never settled within ${timeoutMs}ms (last=${last})`);
}

async function shownCount(page: Page): Promise<number> {
  return stableCount(page);
}

/** Wait for the counter to CHANGE away from `from`, then settle.
 *
 *  Stability alone is not enough after an interaction: the PRE-change value is
 *  already stable, and a 300ms debounce plus a refetch and a re-aggregation of
 *  6,523 files means it stays stable for seconds. A stability-only probe
 *  therefore returns the old number and reports "the filter did nothing" --
 *  which is exactly what the first run of this spec concluded, wrongly. */
async function changedCount(page: Page, from: number, timeoutMs = 180_000): Promise<number> {
  const bar = page.getByText(/Showing [\d,]+ of [\d,]+ files/).first();
  await expect
    .poll(async () => parseShown((await bar.innerText()).trim()),
          { timeout: timeoutMs, intervals: [500] })
    .not.toBe(from);
  return stableCount(page);
}

async function noticeText(page: Page): Promise<string | null> {
  const n = page.getByText(/Graph shows the top|Map shows/);
  return (await n.count()) ? (await n.first().innerText()).replace(/\s+/g, " ") : null;
}

async function openView(page: Page, label: string) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  await counterText(page);
}

/** Toggle a LANGUAGE chip in the filter bar. */
async function toggleLanguage(page: Page, lang: string) {
  await page.getByRole("button", { name: lang, exact: true }).first().click();
}

test("filter reduces the graph on Architecture and Matrix", async ({ page }) => {
  test.setTimeout(300_000);
  await authenticate(page);
  await page.goto("/repos/6");
  await settle(page);

  for (const view of ["Architecture", "Matrix"]) {
    await openView(page, view);

    const before = await shownCount(page);
    const noticeBefore = await noticeText(page);

    // python only -- superset is ~2,547 python of 6,523, so this must reduce.
    await toggleLanguage(page, "python");
    // The debounce is 300ms; the refetch and re-aggregation follow.
    const after = await changedCount(page, before);
    const noticeAfter = await noticeText(page);

    // eslint-disable-next-line no-console
    console.log(`[filter] ${view}: counter ${before} -> ${after} | notice ${JSON.stringify(noticeBefore)} -> ${JSON.stringify(noticeAfter)}`);

    // DISCRIMINATION: the probe saw the counter CHANGE, so it can perceive the
    // filter. If these were equal the assertion above would already have timed
    // out -- stated explicitly so the proof is in the record, not implied.
    expect(after, `${view}: filter must reduce the counted file set`).toBeLessThan(before);
    expect(after, `${view}: python subset of superset should be in the low thousands`)
      .toBeGreaterThan(0);

    // DetailPanel is fed by BOTH surfaces (Architecture via layeredLayout,
    // Matrix via matrixLayout) -- the §17.28 coupling. It must still render.
    const panel = page.getByText(/Select a directory on the Architecture map/);
    expect(await panel.count(), `${view}: DetailPanel must survive the filter`)
      .toBeGreaterThan(0);

    // Reset for the next surface.
    await toggleLanguage(page, "python");
    const restored = await changedCount(page, after);
    expect(restored, `${view}: clearing the filter must restore the full count`).toBe(before);
  }
});
