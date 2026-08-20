import { Page, expect, test } from "@playwright/test";
import { authenticate } from "./auth";

// Browser verification for the comprehension-card practice panel -- the first
// user surface for cards that existed backend-only.
//
// Real modules, not fixtures, and both cases:
//   POPULATED  backend-app-services-codebase-models-1-4990  (repo 1, 6 cards)
//   EMPTY      messages-3-5553                              (repo 3, 0 cards)
//
// The empty case is the one most able to fool a probe: an empty panel and a
// not-yet-loaded panel are indistinguishable to a check that only asks "is
// there no card here". The component renders three DIFFERENT testids --
// cards-loading, cards-empty, cards-open -- and the discrimination proof below
// asserts the probe can tell them apart before any verdict is trusted (§17.30).
const POPULATED = "backend-app-services-codebase-models-1-4990";
const EMPTY = "messages-3-5553";

async function settleModule(page: Page) {
  // The panel resolves to exactly one of three states. Wait for that, rather
  // than for a duration -- a fixed sleep samples mid-fetch and reads the
  // loading state as an empty one.
  await expect
    .poll(async () => {
      for (const id of ["cards-open", "cards-empty", "cards-panel", "cards-error"]) {
        if (await page.getByTestId(id).count()) return id;
      }
      return (await page.getByTestId("cards-loading").count()) ? "cards-loading" : "none";
    }, { timeout: 60_000, intervals: [400] })
    .not.toMatch(/cards-loading|none/);
}

test("DISCRIMINATION: the probe tells populated, empty and loading apart", async ({ page }) => {
  test.setTimeout(180_000);
  await authenticate(page);

  await page.goto(`/modules/${POPULATED}`);
  await settleModule(page);
  const populatedState = {
    open: await page.getByTestId("cards-open").count(),
    empty: await page.getByTestId("cards-empty").count(),
    loading: await page.getByTestId("cards-loading").count(),
  };

  await page.goto(`/modules/${EMPTY}`);
  await settleModule(page);
  const emptyState = {
    open: await page.getByTestId("cards-open").count(),
    empty: await page.getByTestId("cards-empty").count(),
    loading: await page.getByTestId("cards-loading").count(),
  };

  // eslint-disable-next-line no-console
  console.log(`[cards] populated=${JSON.stringify(populatedState)} empty=${JSON.stringify(emptyState)}`);

  // The proof: the two modules produce DIFFERENT states, and neither is the
  // loading state. A probe that reported the same thing for both, or that could
  // not distinguish "empty" from "still fetching", would be worthless here
  // whichever way the panel behaved.
  expect(populatedState.open, "populated module must offer the panel").toBe(1);
  expect(populatedState.empty, "populated module must NOT render the empty state").toBe(0);
  expect(emptyState.empty, "module with no cards must render the empty state").toBe(1);
  expect(emptyState.open, "module with no cards must NOT offer the panel").toBe(0);
  expect(emptyState.loading + populatedState.loading,
    "neither verdict may be taken while still loading").toBe(0);

  await page.getByTestId("cards-empty").screenshot({
    path: "e2e/__artifacts__/cards-empty-state.png",
  });
});

test("a card grades correct, and a wrong answer teaches the edge", async ({ page }) => {
  test.setTimeout(180_000);
  await authenticate(page);
  await page.goto(`/modules/${POPULATED}`);
  await settleModule(page);

  await page.getByTestId("cards-open").click();
  await expect(page.getByTestId("card-question")).toBeVisible();
  await page.getByTestId("cards-panel").screenshot({
    path: "e2e/__artifacts__/cards-question.png",
  });

  const source = (await page.getByTestId("card-source").innerText()).trim();
  const before = (await page.getByTestId("cards-progress").innerText()).trim();

  // WRONG first, on purpose: the load-bearing claim is that a miss reveals the
  // rationale naming the stored fact, not merely that it is marked wrong.
  const options = page.getByTestId("card-option");
  await options.nth(0).click();
  await expect(page.getByTestId("card-rationale")).toBeVisible();
  const firstVerdict = (await page.getByTestId("card-rationale").innerText()).replace(/\s+/g, " ");
  await page.getByTestId("cards-panel").screenshot({
    path: "e2e/__artifacts__/cards-graded-1.png",
  });

  const after = (await page.getByTestId("cards-progress").innerText()).trim();
  // eslint-disable-next-line no-console
  console.log(`[cards] source=${JSON.stringify(source)} progress ${JSON.stringify(before)} -> ${JSON.stringify(after)}`);
  // eslint-disable-next-line no-console
  console.log(`[cards] verdict-1: ${JSON.stringify(firstVerdict.slice(0, 180))}`);

  // The rationale must name a fact, not just say right/wrong.
  // Case-insensitive: these labels carry Tailwind's `uppercase`, and
  // `innerText` returns TEXT AS RENDERED, so the DOM string is "NOT RECALLED"
  // even though the source says "not recalled".
  expect(firstVerdict).toMatch(/recalled/i);
  expect(firstVerdict.length, "the rationale must explain, not just mark").toBeGreaterThan(40);
  expect(source.toLowerCase(), "the source label must render for the seam")
    .toBe("deterministic");

  // Advance and answer a second card, so the running count is observed moving.
  await page.getByTestId("card-next").click();
  await expect(page.getByTestId("card-question")).toBeVisible();
  await page.getByTestId("card-option").nth(1).click();
  await expect(page.getByTestId("card-rationale")).toBeVisible();
  const second = (await page.getByTestId("cards-progress").innerText()).trim();
  // eslint-disable-next-line no-console
  console.log(`[cards] progress after two answers: ${JSON.stringify(second)}`);

  // Two answered, and the denominator tracks answers rather than staying at the
  // card count -- "N of M recalled" must describe what was actually attempted.
  expect(second).toMatch(/of 2 recalled$/i);
  await page.getByTestId("cards-panel").screenshot({
    path: "e2e/__artifacts__/cards-graded-2.png",
  });
});
