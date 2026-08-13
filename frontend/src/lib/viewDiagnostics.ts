// State worth having at the moment a ViewBoundary catches something.
//
// Written for one specific open item: a `Cannot read properties of undefined
// (reading 'index')` in the Dependency Graph, reported once, boundary-caught,
// and never reproduced -- across three scripted attempts and one manual repeat
// of the exact user sequence (scroll, click a CLUSTER chip, unclick the same
// chip). See decisions.md.
//
// The next occurrence should be diagnosable from what the boundary logs rather
// than from a fifth guessing session, so the boundary needs facts the throw
// itself does not carry: which filters were on, how many elements cytoscape was
// handed, and -- the one that actually discriminates between the surviving
// hypotheses -- whether an ELK layout was still running when it blew up.
//
// A module-level mutable record rather than React context or props: the
// interesting values live inside DependencyGraph (element counts, layout state)
// while the boundary that catches sits ABOVE it, so at catch time the component
// holding them has already been torn down. A value written here survives that.
// It is diagnostic-only and nothing renders from it.

export type LayoutPhase = "idle" | "running";

export type ViewDiagnostics = {
  /** Elements handed to cytoscape on the last update. */
  graphNodeCount: number | null;
  graphEdgeCount: number | null;
  /** "running" means an async ELK layout had been started and had not reported
   * layoutstop. An outstanding layout at throw time is what would support the
   * stale-layout hypothesis; none present refutes it. */
  layoutPhase: LayoutPhase;
  /** How many times a new layout was started before the previous one finished.
   * Zero across a session means layouts never overlap and the hypothesis is
   * dead regardless of what else is true. */
  layoutRestartsWhileRunning: number;
  showFullGraph: boolean | null;
  focusCount: number | null;
  /** Monotonic ms since the last layout was started, filled in when read. */
  msSinceLayoutStart: number | null;
};

const state: ViewDiagnostics & { _layoutStartedAt: number | null } = {
  graphNodeCount: null,
  graphEdgeCount: null,
  layoutPhase: "idle",
  layoutRestartsWhileRunning: 0,
  showFullGraph: null,
  focusCount: null,
  msSinceLayoutStart: null,
  _layoutStartedAt: null,
};

export function recordGraphElements(nodes: number, edges: number, opts: {
  showFullGraph: boolean;
  focusCount: number;
}): void {
  state.graphNodeCount = nodes;
  state.graphEdgeCount = edges;
  state.showFullGraph = opts.showFullGraph;
  state.focusCount = opts.focusCount;
}

export function recordLayoutStarted(): void {
  // Counted BEFORE the phase is overwritten: starting a layout while one is
  // already running is the overlap the open item turns on, and it is invisible
  // once the phase has been set to "running" twice.
  if (state.layoutPhase === "running") state.layoutRestartsWhileRunning += 1;
  state.layoutPhase = "running";
  state._layoutStartedAt = performance.now();
}

export function recordLayoutSettled(): void {
  state.layoutPhase = "idle";
}

/** Snapshot for a boundary to log. Never throws -- a diagnostic that can fail
 * while reporting a failure is worse than none. */
export function readViewDiagnostics(): ViewDiagnostics {
  try {
    return {
      graphNodeCount: state.graphNodeCount,
      graphEdgeCount: state.graphEdgeCount,
      layoutPhase: state.layoutPhase,
      layoutRestartsWhileRunning: state.layoutRestartsWhileRunning,
      showFullGraph: state.showFullGraph,
      focusCount: state.focusCount,
      msSinceLayoutStart:
        state._layoutStartedAt === null ? null : Math.round(performance.now() - state._layoutStartedAt),
    };
  } catch {
    return {
      graphNodeCount: null, graphEdgeCount: null, layoutPhase: "idle",
      layoutRestartsWhileRunning: 0, showFullGraph: null, focusCount: null,
      msSinceLayoutStart: null,
    };
  }
}
