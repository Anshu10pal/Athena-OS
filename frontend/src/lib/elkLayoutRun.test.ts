import { describe, expect, it, vi } from "vitest";
import { LayoutNodeT, LayoutTargetT, runElkLayout } from "./elkLayoutRun";

// A layout is asynchronous and the graph it was computed for can be replaced
// while it is still running. These pin what happens to a result that arrives
// after that replacement: it must be discarded, never painted onto whatever is
// on screen now.
//
// Canaried, per §15.1, by deleting the `if (cancelled) return;` guard in
// elkLayoutRun.ts and confirming the load-bearing tests below FAIL -- a
// cancellation test that still passes without the guard is testing nothing.

/** A cytoscape stand-in that records what was done to it. Narrow by design:
 *  runElkLayout only positions leaves and fits, so anything else being called
 *  would itself be the finding. */
function fakeCy(nodeIds: string[] = ["a", "b"]) {
  const applied: Array<Record<string, { x: number; y: number }>> = [];
  const fits: number[] = [];
  const nodes: LayoutNodeT[] = nodeIds.map((id) => ({
    id: () => id,
    isParent: () => false,
    position: () => ({ x: -1, y: -1 }),
  }));
  const cy: LayoutTargetT = {
    nodes: () => ({
      toArray: () => nodes,
      filter: (predicate: (n: LayoutNodeT) => boolean) => ({
        positions: (fn: (n: LayoutNodeT) => { x: number; y: number }) => {
          const batch: Record<string, { x: number; y: number }> = {};
          for (const n of nodes.filter(predicate)) batch[n.id()] = fn(n);
          applied.push(batch);
        },
      }),
    }),
    edges: () => ({ toArray: () => [] }),
    fit: (_p, v) => fits.push(v ?? 0),
  };
  return { cy, applied, fits };
}

/** A promise whose settlement this test controls, so "the result arrives after
 *  cancellation" is deterministic rather than a race. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const POSITIONS = new Map([
  ["a", { x: 10, y: 20 }],
  ["b", { x: 30, y: 40 }],
]);

describe("runElkLayout cancellation lifecycle", () => {
  it("applies positions and fits when it is NOT cancelled", async () => {
    const { cy, applied, fits } = fakeCy();
    const d = deferred<Map<string, { x: number; y: number }>>();
    const onSettled = vi.fn();
    const onError = vi.fn();

    runElkLayout(cy, {}, { compute: () => d.promise, onSettled, onError });
    d.resolve(POSITIONS);
    await d.promise;
    await Promise.resolve();

    // Establishes the test can observe application at all -- without this, the
    // cancellation assertions below would pass on a broken fake.
    expect(applied).toEqual([{ a: { x: 10, y: 20 }, b: { x: 30, y: 40 } }]);
    expect(fits).toEqual([40]);
    expect(onError).not.toHaveBeenCalled();
  });

  it("LOADBEARING: a result arriving after cancel is not applied", async () => {
    const { cy, applied, fits } = fakeCy();
    const d = deferred<Map<string, { x: number; y: number }>>();
    const onSettled = vi.fn();
    const onError = vi.fn();

    const cancel = runElkLayout(cy, {}, { compute: () => d.promise, onSettled, onError });
    // The graph this layout was computed for is replaced BEFORE ELK returns.
    cancel();
    d.resolve(POSITIONS);
    await d.promise;
    await Promise.resolve();

    expect(applied).toEqual([]);
    expect(fits).toEqual([]);
  });

  it("LOADBEARING: a rejection arriving after cancel is not reported", async () => {
    const { cy } = fakeCy();
    const d = deferred<Map<string, { x: number; y: number }>>();
    const onSettled = vi.fn();
    const onError = vi.fn();

    const cancel = runElkLayout(cy, {}, { compute: () => d.promise, onSettled, onError });
    cancel();
    d.reject(new Error("elk exploded"));
    await d.promise.catch(() => undefined);
    await Promise.resolve();

    // A cancelled run's failure is not the user's problem: the graph it was
    // computed for is already gone, so surfacing it would report an error
    // about something nobody is looking at.
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports a rejection that arrives while still live", async () => {
    const { cy } = fakeCy();
    const d = deferred<Map<string, { x: number; y: number }>>();
    const onSettled = vi.fn();
    const onError = vi.fn();

    runElkLayout(cy, {}, { compute: () => d.promise, onSettled, onError });
    const boom = new Error("elk exploded");
    d.reject(boom);
    await d.promise.catch(() => undefined);
    await Promise.resolve();

    expect(onError).toHaveBeenCalledWith(boom);
  });

  it("LOADBEARING: the SECOND run's positions win when both resolve out of order", async () => {
    // The real sequence behind a narrow-then-widen transition: run A starts,
    // elements change, run B starts, then A resolves LAST. Ordering by arrival
    // would paint the stale layout over the current graph.
    const { cy, applied } = fakeCy();
    const first = deferred<Map<string, { x: number; y: number }>>();
    const second = deferred<Map<string, { x: number; y: number }>>();
    const noop = vi.fn();

    const cancelFirst = runElkLayout(
      cy, {}, { compute: () => first.promise, onSettled: noop, onError: noop });
    cancelFirst();
    runElkLayout(
      cy, {}, { compute: () => second.promise, onSettled: noop, onError: noop });

    second.resolve(new Map([["a", { x: 1, y: 1 }], ["b", { x: 2, y: 2 }]]));
    await second.promise;
    await Promise.resolve();
    first.resolve(POSITIONS); // the stale one, arriving late
    await first.promise;
    await Promise.resolve();

    expect(applied).toEqual([{ a: { x: 1, y: 1 }, b: { x: 2, y: 2 } }]);
  });

  it("settles the diagnostic exactly once whether applied or cancelled", async () => {
    // A run that settles without saying so leaves the diagnostics claiming a
    // layout is in flight forever, which is what viewDiagnostics is read for.
    const applyCase = fakeCy();
    const dApply = deferred<Map<string, { x: number; y: number }>>();
    const settledApply = vi.fn();
    runElkLayout(applyCase.cy, {}, {
      compute: () => dApply.promise, onSettled: settledApply, onError: vi.fn(),
    });
    dApply.resolve(POSITIONS);
    await dApply.promise;
    await Promise.resolve();
    expect(settledApply).toHaveBeenCalledTimes(1);

    const cancelCase = fakeCy();
    const dCancel = deferred<Map<string, { x: number; y: number }>>();
    const settledCancel = vi.fn();
    const cancel = runElkLayout(cancelCase.cy, {}, {
      compute: () => dCancel.promise, onSettled: settledCancel, onError: vi.fn(),
    });
    cancel();
    dCancel.resolve(POSITIONS);
    await dCancel.promise;
    await Promise.resolve();
    expect(settledCancel).toHaveBeenCalledTimes(1);
  });

  it("positions only leaves, never parent nodes", async () => {
    const parent: LayoutNodeT = {
      id: () => "p", isParent: () => true, position: () => ({ x: 0, y: 0 }),
    };
    const leaf: LayoutNodeT = {
      id: () => "a", isParent: () => false, position: () => ({ x: -1, y: -1 }),
    };
    const nodes = [parent, leaf];
    const applied: Array<Record<string, { x: number; y: number }>> = [];
    const cy: LayoutTargetT = {
      nodes: () => ({
        toArray: () => nodes,
        filter: (p: (n: LayoutNodeT) => boolean) => ({
          positions: (fn: (n: LayoutNodeT) => { x: number; y: number }) => {
            const batch: Record<string, { x: number; y: number }> = {};
            for (const n of nodes.filter(p)) batch[n.id()] = fn(n);
            applied.push(batch);
          },
        }),
      }),
      edges: () => ({ toArray: () => [] }),
      fit: () => undefined,
    };
    const d = deferred<Map<string, { x: number; y: number }>>();
    runElkLayout(cy, {}, { compute: () => d.promise, onSettled: vi.fn(), onError: vi.fn() });
    d.resolve(POSITIONS);
    await d.promise;
    await Promise.resolve();

    expect(Object.keys(applied[0])).toEqual(["a"]);
  });

  it("falls back to a node's own position when ELK omits it", async () => {
    const { cy, applied } = fakeCy(["a", "missing"]);
    const d = deferred<Map<string, { x: number; y: number }>>();
    runElkLayout(cy, {}, { compute: () => d.promise, onSettled: vi.fn(), onError: vi.fn() });
    d.resolve(new Map([["a", { x: 5, y: 5 }]]));
    await d.promise;
    await Promise.resolve();

    expect(applied[0]).toEqual({ a: { x: 5, y: 5 }, missing: { x: -1, y: -1 } });
  });
});
