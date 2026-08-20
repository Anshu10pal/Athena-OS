import { expect, test } from "@playwright/test";
import { authenticate } from "./auth";
import { settle } from "./settle";

// Resolves a question a CDP probe could not answer: it reported `svg g = 0`
// and `canvas = 0` for the Architecture tab and could not distinguish "the tab
// did not render" from "it renders through elements the probe did not count".
// ArchitectureMap.tsx:458 does emit an <svg>, so the probe was most likely
// counting the wrong child element -- but "most likely" is not a measurement,
// and :682 is about to ship filter wiring to this surface.
//
// Repo 6 (apache/superset, 6,523 files) on purpose: the largest corpus
// available, so a size-dependent render failure has somewhere to show up.
test("Architecture renders a real map on the largest repo", async ({ page }) => {
  await authenticate(page);
  await page.goto("/repos/6");
  await settle(page);

  // Two controls carry this exact label: the tab strip button (from
  // RepoDetail's VIEWS array) and a shortcut card in the Overview body. Taking
  // `.first()` is the tab strip -- the shortcut is rendered later in the
  // document. Discovered by a strict-mode violation rather than assumed, which
  // is the whole reason not to hand-roll a `[...querySelectorAll].find()`: it
  // would have silently taken one of the two.
  await page.getByRole("button", { name: "Architecture", exact: true }).first().click();

  const svg = page.locator("svg").filter({ has: page.locator("rect") }).first();
  await expect(svg).toBeVisible();

  const shape = await page.evaluate(() => {
    const svgs = [...document.querySelectorAll("svg")];
    const map = svgs
      .map((s) => ({ el: s, rects: s.querySelectorAll("rect").length }))
      .sort((a, b) => b.rects - a.rects)[0];
    const s = map?.el;
    return {
      svg_count: svgs.length,
      canvas_count: document.querySelectorAll("canvas").length,
      // What the CDP probe actually looked for, kept so the two are comparable.
      svg_g: document.querySelectorAll("svg g").length,
      map_rects: s ? s.querySelectorAll("rect").length : 0,
      map_texts: s ? s.querySelectorAll("text").length : 0,
      map_paths: s ? s.querySelectorAll("path, line, polyline").length : 0,
      viewBox: s ? s.getAttribute("viewBox") : null,
    };
  });
  // eslint-disable-next-line no-console
  console.log("[architecture] rendered shape:", JSON.stringify(shape));

  // A map with directory boxes and labels, not an empty frame.
  expect(shape.map_rects).toBeGreaterThan(5);
  expect(shape.map_texts).toBeGreaterThan(5);

  await page.screenshot({ path: "e2e/__artifacts__/architecture-repo6.png", fullPage: false });
});
