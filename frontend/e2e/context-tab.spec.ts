import { expect, test } from "@playwright/test";

import { authenticate } from "./auth";
import { settle } from "./settle";

// Phase 8 checkpoint 3b-2. The FIRST checkpoint whose binding constraint is
// visual, so this is the first spec that exists to confirm something is on
// screen rather than that a number is right.
//
// repo 6 = apache/superset at a05a0999; file 2256 = superset/models/core.py,
// 274 connected (134 source importers + 124 test importers + 16 imports,
// 6 of which are both-direction), 51 unresolved specifiers.
const URL = "/repos/6?view=context&fileId=2256";

test.describe("Context tab", () => {
  test.beforeEach(async ({ page }) => {
    await authenticate(page);
  });

  test("the reconciliation is readable on screen", async ({ page }) => {
    await page.goto(URL);
    await settle(page);

    const recon = page.getByTestId("ctx-reconcile");
    await expect(recon).toBeVisible();
    const text = (await recon.textContent()) ?? "";
    // D22's binding constraint: the split must be VISIBLE, not inferable.
    expect(text).toContain("134");
    expect(text).toContain("124");
    expect(text).toContain("258");
    expect(text).toContain("274");
    expect(text).not.toContain("DO NOT RECONCILE");
  });

  test("all three trays report their own totals", async ({ page }) => {
    await page.goto(URL);
    await settle(page);
    await expect(page.getByTestId("tray-imports")).toContainText("16");
    await expect(page.getByTestId("tray-source")).toContainText("134");
    await expect(page.getByTestId("tray-tests")).toContainText("124");
    // the source tray folds, the tests tray does not (only 2 folders).
    // Wording changed at the layout pass: the sub-line used to read
    // "134 ... all 3 shown", which mixed FILES and FOLDERS and read as a
    // contradiction. It now names both. The property asserted is the same.
    await expect(page.getByTestId("tray-source")).toContainText("folded");
    await expect(page.getByTestId("tray-tests")).toContainText("in 2 folders, all drawn");
  });

  test("the graph renders a centre node and both sides", async ({ page }) => {
    await page.goto(URL);
    await settle(page);
    const graph = page.getByTestId("ctx-graph");
    await expect(graph).toBeVisible();
    // cytoscape draws to a canvas, so assert the canvas mounted and has pixels
    // rather than querying for DOM nodes that do not exist.
    const canvases = graph.locator("canvas");
    expect(await canvases.count()).toBeGreaterThan(0);
    const box = await graph.boundingBox();
    expect(box!.height).toBeGreaterThan(400);
  });

  test("D17: the unresolved tray is present, labelled, and not a file list", async ({ page }) => {
    await page.goto(URL);
    await settle(page);
    const tray = page.getByTestId("ctx-unresolved");
    await expect(tray).toBeVisible();
    await expect(tray).toContainText("Unresolved imports (51)");
    await expect(tray).toContainText("not files");
    // a real specifier, and NOT a path
    await expect(tray).toContainText("builtins");
  });
});

// ---------------------------------------------------------------------------
// Checkpoint 3b-3 -- navigation, the D14 fingerprint, and the empty state.
// ---------------------------------------------------------------------------

const FP_2256 = "?view=context&fileId=2256&fp=";

test.describe("Context tab -- navigation and D14", () => {
  test.beforeEach(async ({ page }) => { await authenticate(page); });

  test("the empty state offers hubs AND the barely-connected file (D23)", async ({ page }) => {
    await page.goto("/repos/6?view=context");
    await settle(page);
    const empty = page.getByTestId("ctx-empty");
    await expect(empty).toBeVisible();
    // rank-ordered hubs
    expect(await page.getByTestId("ctx-empty-top").count()).toBeGreaterThan(0);
    // and the floor, which a top-N list can never reach (rank 3,736 of 6,584)
    const floor = page.getByTestId("ctx-empty-floor");
    await expect(floor).toBeVisible();
    await expect(floor).toContainText("scripts/__init__.py");
    await expect(empty).toContainText("other end of the range");
  });

  test("the floor file renders, and says it has no connections", async ({ page }) => {
    await page.goto("/repos/6?view=context");
    await settle(page);
    await page.getByTestId("ctx-empty-floor").click();
    await expect(page.getByTestId("ctx-no-neighbours")).toBeVisible();
    await expect(page.getByTestId("ctx-reconcile")).toContainText("0");
    await expect(page).toHaveURL(/fileId=1107/);
    await expect(page).toHaveURL(/fp=/);
  });

  test("a wrong fingerprint gives the explicit changed-file state", async ({ page }) => {
    // deliberately wrong fp for file 2256
    await page.goto("/repos/6?view=context&fileId=2256&fp=zzzzzz");
    await settle(page);
    const m = page.getByTestId("ctx-fp-mismatch");
    await expect(m).toBeVisible();
    await expect(m).toContainText("points at a file that has changed");
    await expect(m).toContainText("zzzzzz");
    await expect(m).toContainText("superset/models/core.py");
    // and the graph is NOT rendered for the wrong file
    await expect(page.getByTestId("ctx-graph")).toHaveCount(0);
  });

  test("a correct fingerprint renders normally", async ({ page }) => {
    await page.goto("/repos/6?view=context");
    await settle(page);
    await page.getByTestId("ctx-empty-top").first().click();
    await expect(page.getByTestId("ctx-fp-mismatch")).toHaveCount(0);
    await expect(page.getByTestId("ctx-graph")).toBeVisible();
  });

  // REMOVED: a Playwright test that clicked a guessed pixel coordinate to hit a
  // collapsed group. It passed or failed on where ELK happened to place the
  // node, which is a test whose verdict is luck -- §17.37's own warning applied
  // to an interaction rather than a rendering. The DECISION is covered
  // deterministically in contextNav.test.ts (`actionForNode`: single file
  // navigates, group drills, centre says so), and the drill-in itself was
  // verified by OBSERVATION in a browser and recorded in decisions.md, which
  // is what §17.37 asks for. Exposing the cytoscape instance on `window` to
  // make this scriptable was rejected: production surface added for a test.

  test("reload at a deep URL renders the same neighbourhood", async ({ page }) => {
    await page.goto("/repos/6?view=context&fileId=2419");
    await settle(page);
    const before = await page.getByTestId("ctx-reconcile").textContent();
    await page.reload();
    await settle(page);
    const after = await page.getByTestId("ctx-reconcile").textContent();
    expect(after).toBe(before);
    expect(after).toContain("355");
  });
});
