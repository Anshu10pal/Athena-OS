import { expect, Page } from "@playwright/test";

// Wait until the repo page is genuinely INTERACTIVE, not merely rendered.
//
// This exists because of a real, twice-hit failure. Playwright's auto-wait
// guarantees a control is attached, visible and stable before clicking -- it
// cannot know whether React has attached the control's `onClick` yet. Clicking
// a rendered-but-unhydrated button is a silent no-op: the click "succeeds",
// nothing happens, and the subsequent assertion fails somewhere else entirely,
// pointing at the wrong thing.
//
// It cost two wrong diagnoses before it was understood. A raw CDP probe run
// earlier reported `svg g = 0` for the Architecture tab and was read as
// "Architecture may not render"; the first Playwright version of that test
// failed waiting 30s for an SVG. Both were the same no-op click. Architecture
// renders fine (878x558, 54 rects, 54 texts, 43 groups on apache/superset).
//
// The tab-strip probe is the signal: RepoDetail renders it from its VIEWS
// array, so its presence means that component's tree is mounted. The extra
// settle covers the effect pass that follows mount.
export async function settle(page: Page): Promise<void> {
  await expect(
    page.getByRole("button", { name: "Overview", exact: true }).first(),
  ).toBeVisible();
  await page.waitForTimeout(2500);
}
