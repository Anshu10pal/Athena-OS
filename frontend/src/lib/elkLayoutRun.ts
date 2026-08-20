// The cancellation lifecycle around an ELK layout run.
//
// Extracted from DependencyGraph's elements effect so it can be tested without
// a DOM. The behaviour it owns is small and entirely about ORDERING: a layout
// is asynchronous, the graph it was computed for can be replaced while it is
// still running, and a result that arrives after that replacement must be
// thrown away rather than painted onto whatever is now on screen.
//
// Why this is not merely tidy: the caller's next run does
// `cy.elements().remove()` and re-adds a fresh set, so a late `.then` would
// position either objects that no longer exist or -- worse, because element
// ids repeat across scope changes -- the WRONG generation of elements, which
// shows up as a flash of the previous graph's layout.
//
// `compute` is injected rather than imported. That is the seam this module
// exists for: the real implementation spawns a Web Worker, and a test that had
// to stand one up would be testing elkjs rather than the discard rule. The
// production call site passes `computeElkLayout` unchanged.
//
// Deliberately NOT claimed as the fix for the reported
// `Cannot read properties of undefined (reading 'index')` crash. That crash has
// never been reproduced. Uncancelled async work in an effect is wrong whether
// or not it is what was seen; see decisions.md, where the two are recorded
// separately for exactly this reason.

/** The slice of a cytoscape core this module touches. Narrow on purpose: it
 *  keeps the module free of a cytoscape import, and it documents that nothing
 *  here reads or mutates the graph beyond positioning leaves and fitting. */
export interface LayoutTargetT {
  nodes(): {
    toArray(): unknown[];
    filter(predicate: (n: LayoutNodeT) => boolean): {
      positions(fn: (n: LayoutNodeT) => { x: number; y: number }): void;
    };
  };
  edges(): { toArray(): unknown[] };
  fit(padding?: undefined, value?: number): void;
}

export interface LayoutNodeT {
  id(): string;
  isParent(): boolean;
  position(): { x: number; y: number };
}

export interface RunElkLayoutDepsT {
  /** Injected `computeElkLayout`. */
  compute: (
    nodes: unknown[],
    edges: unknown[],
    options: Record<string, string>,
  ) => Promise<Map<string, { x: number; y: number }>>;
  /** Diagnostic hook, called exactly once per run whichever way it ends --
   *  applied, rejected, or cancelled. A run that settles without saying so
   *  leaves the diagnostics claiming a layout is still in flight forever. */
  onSettled: () => void;
  /** A rejected layout must not fail silently: without this, ELK erroring on
   *  some graph shape leaves every node at its default position with nothing
   *  surfaced -- indistinguishable from "still loading" to whoever is looking. */
  onError: (err: unknown) => void;
}

/**
 * Starts a layout and returns its CANCEL function.
 *
 * The returned function is the effect cleanup. Calling it means "the graph this
 * layout was computed for is gone" -- after which the pending result must not
 * be applied, and neither `positions` nor `fit` may be called.
 */
export function runElkLayout(
  cy: LayoutTargetT,
  options: Record<string, string>,
  deps: RunElkLayoutDepsT,
): () => void {
  let cancelled = false;

  deps
    .compute(cy.nodes().toArray(), cy.edges().toArray(), options)
    .then((positions) => {
      if (cancelled) return;
      cy.nodes()
        .filter((n) => !n.isParent())
        .positions((n) => positions.get(n.id()) ?? n.position());
      deps.onSettled();
      // Fit AFTER positions are applied, not before, or the viewport is fitted
      // to pre-layout positions.
      cy.fit(undefined, 40);
    })
    .catch((err) => {
      if (cancelled) return;
      deps.onSettled();
      deps.onError(err);
    });

  return () => {
    cancelled = true;
    deps.onSettled();
  };
}
