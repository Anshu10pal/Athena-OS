import { expect, Page, test } from "@playwright/test";
import { authenticate } from "./auth";
import { settle } from "./settle";

// Checkpoint 4, item 2: the Layers view renders from the 400-capped node array
// while its counter reports the full post-filter total, and says nothing about
// the gap. Dependency Graph, reading the same `/graph` response, does say so.
//
// `ARTIFACT` names the screenshot so the same spec can be run before the fix,
// after it, and under the §15.1 canary, producing comparable images.
const ARTIFACT = process.env.NOTICE_ARTIFACT ?? "unnamed";

/** The filter-bar block: counter, then the truncation notice when there is one.
 *  Anchored on the counter's text rather than a class, because classes here are
 *  Tailwind utility soup and would match several unrelated blocks. */
function noticeRegion(page: Page) {
  return page.locator("div").filter({
    has: page.getByText(/Showing [\d,]+ of [\d,]+ files/),
  }).last();
}

async function gotoView(page: Page, label: string) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  // The hydration wait exists for a reason -- see e2e/settle.ts.
  await page.waitForTimeout(6000);
}

async function report(page: Page, view: string) {
  const counter = await page.getByText(/Showing [\d,]+ of [\d,]+ files/).first().innerText();
  const notices = page.getByText(/Graph shows the top|Map shows/);
  const count = await notices.count();
  const text = count ? (await notices.first().innerText()).replace(/\s+/g, " ") : null;
  await noticeRegion(page).screenshot({
    path: `e2e/__artifacts__/notice-${ARTIFACT}-${view}.png`,
  });
  // eslint-disable-next-line no-console
  console.log(`[notice] ${view}: counter=${JSON.stringify(counter)} notice=${JSON.stringify(text)}`);
  return { counter, notice: text };
}

test("truncation notice: Layers vs Dependency Graph", async ({ page }) => {
  test.setTimeout(240_000);
  await authenticate(page);
  await page.goto("/repos/6");
  await settle(page);

  await gotoView(page, "Layers");
  const layers = await report(page, "layers");

  await gotoView(page, "Dependency Graph");
  const depgraph = await report(page, "depgraph");

  // DISCRIMINATION PROOF, run BEFORE any code change: the screenshot and the
  // locator must be able to SEE a notice where one exists. Dependency Graph is
  // the positive control. If this assertion fails, the instrument cannot
  // perceive the thing the fix is supposed to add, and no result from it later
  // would mean anything -- §17.30.
  expect(depgraph.notice, "positive control: Dependency Graph must show a notice")
    .toMatch(/Graph shows the top/);

  // Layers AGAIN, now that the /graph fetch has certainly completed. This
  // separates "the counter is wrong" from "the counter had not loaded yet when
  // the first sample was taken" -- the first visit landed on Layers before the
  // graph response arrived, which is a property of the probe, not the product.
  await gotoView(page, "Layers");
  const layersWarm = await report(page, "layers-warm");

  // eslint-disable-next-line no-console
  console.log(`[notice] DISCRIMINATION: layers=${layers.notice === null ? "absent" : "present"} ` +
    `depgraph=${depgraph.notice === null ? "absent" : "present"} ` +
    `layersWarm=${layersWarm.notice === null ? "absent" : "present"}`);
});
