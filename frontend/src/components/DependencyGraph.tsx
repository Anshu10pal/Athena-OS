import { useEffect, useMemo, useState } from "react";
import cytoscape, { Core, ElementDefinition } from "cytoscape";
import { GraphEdgeT, GraphNodeT } from "../lib/api";
import { clusterColor } from "./ArchitectureMap";
import { buildGraphElements, CyNodeData, expandableDirs } from "../lib/dependencyGraphElements";
import { GraphDirectionT, MAX_NODES_ADVISORY, scopeGraph } from "../lib/dependencyGraphScope";
import { LayoutTargetT, RunElkLayoutDepsT, runElkLayout } from "../lib/elkLayoutRun";
import { computeElkLayout } from "../lib/elkWorkerLayout";
import { recordGraphElements, recordLayoutSettled, recordLayoutStarted } from "../lib/viewDiagnostics";

// Phase J1: the file-level dependency graph, rebuilt as a scoped explorer.
//
// The old force-directed "Raw" view was deleted in H5 for a recorded
// reason -- rendering all N files at once answered none of the three
// questions it was tested against. This view is not that view with a
// nicer layout engine; the difference that matters is that it never shows
// the whole graph by default. It shows one focus and one or two hops, with
// folders collapsed, and every widening is an explicit act.
//
// Layout is ELK "layered" left-to-right, not force simulation: horizontal
// position then encodes dependency direction (importers left, imports
// right) instead of being an artifact of where the simulation happened to
// settle. Same reasoning that replaced force with a computed layout at the
// directory level in H2 -- position should mean something.
//
// The algorithm runs in a Web Worker (lib/elkWorkerLayout.ts), not via
// cytoscape-elk's own `cy.layout({name: 'elk'})`. Measured on this view at
// the 400-node default: the layered algorithm's crossing-minimisation is
// superlinear (t ~ n^2.25 against payload growth of n^1) and cytoscape-elk
// runs it synchronously on the main thread regardless -- a single blocked
// frame of 6.9s at 400 nodes, 82s at 1200. elkjs ships a worker build
// (elk-worker.min.js) already on disk in the same package; the positions
// just have to be read back differently, because a worker-based ELK returns
// a cloned result graph instead of mutating cytoscape-elk's input objects in
// place (see elkPositions.ts and elkWorkerLayout.ts).
//
// All the real logic lives in lib/dependencyGraphScope.ts and
// lib/dependencyGraphElements.ts, unit-tested without a DOM. This file is
// the cytoscape shell and the controls.

// Canvas rendering needs literal color strings, not Tailwind classes --
// the same constraint (and the same values) as ArchitectureMap's
// KIND_COLOR. Every value here is copied from tailwind.config.js, which is
// the source of truth; grep-verified against it rather than eyeballed,
// because a color class that doesn't exist in that config is a bug this
// project has shipped three separate times (`bg-void`).
const COLOR = {
  focus: "#3DDC97", // accent
  cycle: "#E2646E", // danger
  file: "#161D1A", // panel2
  dir: "#101614", // panel
  text: "#E9F1EE", // snow
  textDim: "rgba(233, 241, 238, 0.62)", // fog
  edge: "rgba(233, 241, 238, 0.28)",
  edgeStrong: "rgba(233, 241, 238, 0.5)",
  border: "rgba(255, 255, 255, 0.16)", // edge-2
};

const HOPS_OPTIONS = [1, 2, 3];
const DIRECTIONS: { value: GraphDirectionT; label: string }[] = [
  { value: "both", label: "Both" },
  { value: "imports", label: "Imports" },
  { value: "importedBy", label: "Imported by" },
];

// Deliberately below MAX_NODES_ADVISORY: the default view should be
// comfortably inside the readable range, not sitting exactly at the edge
// of where the warning fires.
const DEFAULT_MAX_NODES = 60;

function cyStyle(): cytoscape.StylesheetStyle[] {
  return [
    {
      selector: "node",
      style: {
        label: "data(label)",
        color: COLOR.text,
        "font-family": "JetBrains Mono, monospace",
        "font-size": 10,
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "text-max-width": "140px",
        shape: "round-rectangle",
        // Tinted by dependency cluster, using the SAME cluster->color
        // mapping as the Architecture map and Matrix (clusterColor, one
        // source of truth) so the three views can never disagree about
        // which color a cluster is. Kept at low opacity: this is a tint
        // that makes the "same cluster" filter legible, not a fill --
        // a saturated background would make the label unreadable.
        "background-color": "data(tint)",
        "background-opacity": 0.22,
        "border-width": 1,
        "border-color": COLOR.border,
        width: "label",
        height: "label",
        padding: "8px",
      },
    },
    {
      // Collapsed folder: visually heavier than a file and labelled with a
      // count, so "this is N things" reads at a glance.
      selector: 'node[kind = "dir"]',
      style: {
        "border-color": COLOR.textDim,
        "font-size": 11,
        shape: "round-rectangle",
      },
    },
    {
      // A collapsed folder whose files span several clusters must not be
      // painted as if it were one clean cluster -- dashed border, same
      // honesty rule (and same trigger) as the Architecture map's
      // cluster-purity treatment.
      selector: "node[?clusterMixed]",
      style: { "border-style": "dashed" },
    },
    {
      // Expanded folder (a cytoscape compound parent). Nearly transparent
      // with a dashed border -- it is a grouping boundary, not an object;
      // painting it solid would compete with the files inside it.
      selector: "node:parent",
      style: {
        "background-color": COLOR.dir,
        "background-opacity": 0.35,
        "border-style": "dashed",
        "border-color": COLOR.textDim,
        "border-width": 1,
        label: "data(label)",
        "text-valign": "top",
        "text-halign": "center",
        "font-size": 9,
        color: COLOR.textDim,
        padding: "14px",
      },
    },
    {
      selector: "node[?isFocus]",
      style: {
        "border-color": COLOR.focus,
        "border-width": 2.5,
        color: COLOR.focus,
      },
    },
    // Distance de-emphasis: further from the focus, quieter. Fades context
    // rather than hiding it -- the specific thing the old force view's
    // dimming got wrong (G4 postmortem).
    { selector: "node[hop = 1]", style: { opacity: 0.9 } },
    { selector: "node[hop >= 2]", style: { opacity: 0.68 } },
    {
      selector: "edge",
      style: {
        width: 1,
        "line-color": COLOR.edge,
        "target-arrow-color": COLOR.edge,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        "curve-style": "bezier",
        opacity: 0.85,
      },
    },
    {
      // Aggregated folder-to-folder edges carry a count; a single edge
      // shows nothing, since "x1" is noise.
      selector: "edge[count > 1]",
      style: {
        label: "data(count)",
        "font-family": "JetBrains Mono, monospace",
        "font-size": 8,
        color: COLOR.textDim,
        "text-background-color": COLOR.file,
        "text-background-opacity": 0.85,
        "text-background-padding": "2px",
        width: 2,
        "line-color": COLOR.edgeStrong,
        "target-arrow-color": COLOR.edgeStrong,
      },
    },
    {
      selector: "edge[?cyclic]",
      style: {
        "line-color": COLOR.cycle,
        "target-arrow-color": COLOR.cycle,
        width: 2,
        opacity: 1,
      },
    },
    {
      selector: "node:selected",
      style: { "border-color": COLOR.focus, "border-width": 2.5 },
    },
  ];
}

function Segmented<T extends string | number>({
  options, value, onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded border border-line p-1 gap-1">
      {options.map((o) => (
        <button
          key={String(o.value)}
          onClick={() => onChange(o.value)}
          className={
            "font-mono text-[10px] uppercase tracking-widest rounded px-2.5 py-1 transition-colors " +
            (value === o.value ? "bg-accent/15 text-accent" : "text-fog hover:text-snow")
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function DependencyGraph({
  nodes, edges, focusIds, focusLabel, onSelectFile, onFocusFile,
}: {
  nodes: GraphNodeT[];
  edges: GraphEdgeT[];
  focusIds: number[];
  focusLabel: string;
  onSelectFile: (fileId: number) => void;
  onFocusFile: (fileId: number) => void;
}) {
  // Both the container node and the cytoscape instance are STATE, not refs,
  // and that is a deliberate correction rather than a style preference.
  // With refs, the init effect ([] deps) ran on mount while the container
  // was still null -- the container only enters the tree once a focus
  // exists -- and then never re-ran once it appeared, so cytoscape was
  // never constructed and the graph box rendered permanently empty. Found
  // in a browser pass, invisible to tsc and to every unit test, since both
  // the scoping and the element-building were correct. Holding both in
  // state lets the dependent effects actually depend on them, which makes
  // the whole ordering hazard unrepresentable instead of merely fixed.
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [cy, setCy] = useState<Core | null>(null);

  const [hops, setHops] = useState(1);
  const [direction, setDirection] = useState<GraphDirectionT>("both");
  const [sameClusterOnly, setSameClusterOnly] = useState(false);
  const [cycleEdgesOnly, setCycleEdgesOnly] = useState(false);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [showFullGraph, setShowFullGraph] = useState(false);

  // Any change to the focus is a change of subject -- folder expansions
  // and the full-graph opt-in belonged to the previous subject and would
  // be actively confusing carried across.
  useEffect(() => {
    setExpandedDirs(new Set());
    setShowFullGraph(false);
  }, [focusIds.join(",")]);

  const scope = useMemo(() => {
    if (showFullGraph) {
      return scopeGraph(nodes, edges, {
        // Seeding from EVERY node (not the focus) is what makes this the
        // whole graph rather than a very wide neighbourhood -- files with
        // no path to the focus at all must appear too, otherwise "full"
        // would be a lie.
        focusIds: nodes.map((n) => n.id),
        hops: 0,
        direction: "both",
        sameClusterOnly: false,
        cycleEdgesOnly,
        maxNodes: nodes.length,
      });
    }
    return scopeGraph(nodes, edges, {
      focusIds, hops, direction, sameClusterOnly, cycleEdgesOnly, maxNodes: DEFAULT_MAX_NODES,
    });
  }, [nodes, edges, focusIds, hops, direction, sameClusterOnly, cycleEdgesOnly, showFullGraph]);

  const elements = useMemo(() => {
    const built = buildGraphElements({
      nodes,
      scopedNodeIds: scope.nodeIds,
      scopedEdges: scope.edges,
      hopOf: scope.hopOf,
      cycleEdgeKeys: scope.cycleEdgeKeys,
      focusIds: showFullGraph ? [] : focusIds,
      expandedDirs,
    });
    const nodeEls: ElementDefinition[] = built.nodes.map((n) => ({
      data: {
        ...n.data,
        // Resolved here rather than in the stylesheet: cytoscape can map a
        // style property from a data field, but it can't call a function
        // per element, so the color has to be precomputed onto the data.
        tint: n.data.clusterId !== null ? clusterColor(n.data.clusterId) : COLOR.file,
        // A collapsed folder shows its count in the label rather than as
        // separate text -- cytoscape has no second-line label slot.
        label: n.data.kind === "dir" && !expandedDirs.has(n.data.path ?? "")
          ? `${n.data.label}\n×${n.data.fileCount}`
          : n.data.label,
      },
    }));
    const edgeEls: ElementDefinition[] = built.edges.map((e) => ({ data: e.data }));
    return [...nodeEls, ...edgeEls];
  }, [nodes, scope, focusIds, expandedDirs, showFullGraph]);

  const dirsAvailable = useMemo(
    () => expandableDirs(nodes, scope.nodeIds),
    [nodes, scope.nodeIds],
  );

  // Init once. StrictMode double-invokes this in dev, so the cleanup has
  // to fully destroy the instance -- otherwise the second mount leaves an
  // orphaned canvas rendering underneath the live one.
  useEffect(() => {
    if (!container) return;
    const instance = cytoscape({
      container,
      style: cyStyle(),
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });
    setCy(instance);
    return () => {
      instance.destroy();
      setCy(null);
    };
  }, [container]);

  // Click a file to select it; click a collapsed folder to expand it --
  // each click does the thing that node visibly affords. Re-centering is
  // double-click, deliberately NOT single-click: a graph that re-scopes
  // itself every time you click to read a label is unusable.
  useEffect(() => {
    if (!cy) return;

    const onTap = (evt: cytoscape.EventObject) => {
      const data = evt.target.data() as CyNodeData;
      if (data.kind === "file" && data.fileId !== undefined) {
        onSelectFile(data.fileId);
      } else if (data.kind === "dir" && data.path) {
        const dir = data.path;
        setExpandedDirs((prev) => {
          const next = new Set(prev);
          if (next.has(dir)) next.delete(dir); else next.add(dir);
          return next;
        });
      }
    };
    const onDoubleTap = (evt: cytoscape.EventObject) => {
      const data = evt.target.data() as CyNodeData;
      if (data.kind === "file" && data.fileId !== undefined) onFocusFile(data.fileId);
    };

    cy.on("tap", "node", onTap);
    cy.on("dbltap", "node", onDoubleTap);
    return () => {
      cy.removeListener("tap", "node", onTap);
      cy.removeListener("dbltap", "node", onDoubleTap);
    };
  }, [cy, onSelectFile, onFocusFile]);

  // Re-render elements and re-run layout whenever the scope changes -- or
  // when cytoscape itself first becomes available, which is why `cy` is a
  // dependency and not a ref read (see the state comment above).
  useEffect(() => {
    if (!cy) return;
    // Diagnostic only -- see lib/viewDiagnostics.ts. Recorded here because a
    // ViewBoundary catching a throw sits above this component and cannot read
    // its state once it has unmounted.
    //
    // Note what this update does: a FULL replacement, not a diff. Whatever
    // cytoscape held is removed and the freshly built set added, so an edge
    // naming a missing node can only come from buildGraphElements itself (which
    // drops them -- see its dangling-edge tests), never from a stale graph.
    // `elements` is a flat ElementDefinition[]; an edge is the one carrying a
    // source, which is cytoscape's own discriminator.
    const edgeCount = elements.filter((el) => (el.data as { source?: string }).source !== undefined).length;
    recordGraphElements(elements.length - edgeCount, edgeCount, {
      showFullGraph,
      focusCount: focusIds.length,
    });
    cy.elements().remove();
    cy.add(elements);
    recordLayoutStarted();

    // Cancel an in-flight layout when `elements` change again.
    //
    // The lifecycle itself lives in lib/elkLayoutRun.ts, which is where it can
    // be tested without a DOM -- `runElkLayout` returns the cancel function and
    // this effect returns it unchanged, so the cleanup React calls on the next
    // run IS the discard. Its module comment carries the full reasoning,
    // including why this is deliberately not claimed as the fix for the
    // reported `Cannot read properties of undefined (reading 'index')` crash.
    return runElkLayout(
      cy as unknown as LayoutTargetT,
      {
        algorithm: "layered",
        // Left-to-right so horizontal position encodes dependency
        // direction: importers on the left, imports on the right. This is
        // the property a force layout cannot give you.
        "elk.direction": "RIGHT",
        "elk.spacing.nodeNode": "32",
        "elk.layered.spacing.nodeNodeBetweenLayers": "72",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
        "elk.padding": "[top=24,left=24,bottom=24,right=24]",
      },
      {
        compute: computeElkLayout as unknown as RunElkLayoutDepsT["compute"],
        onSettled: recordLayoutSettled,
        // eslint-disable-next-line no-console
        onError: (err) => console.error("[DependencyGraph] ELK layout failed", err),
      },
    );
  }, [cy, elements, showFullGraph, focusIds]);

  const hasFocus = focusIds.length > 0 || showFullGraph;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-fog">Hops</span>
          <Segmented
            options={HOPS_OPTIONS.map((h) => ({ value: h, label: String(h) }))}
            value={hops}
            onChange={setHops}
          />
        </div>
        <Segmented options={DIRECTIONS} value={direction} onChange={setDirection} />
        <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-fog cursor-pointer">
          <input
            type="checkbox"
            checked={sameClusterOnly}
            onChange={(e) => setSameClusterOnly(e.target.checked)}
            className="accent-accent"
          />
          Same cluster
        </label>
        <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-fog cursor-pointer">
          <input
            type="checkbox"
            checked={cycleEdgesOnly}
            onChange={(e) => setCycleEdgesOnly(e.target.checked)}
            className="accent-accent"
          />
          Cycle edges only
        </label>
        <button
          onClick={() => setShowFullGraph((v) => !v)}
          className={
            "font-mono text-[10px] uppercase tracking-widest rounded px-2.5 py-1.5 border transition-colors " +
            (showFullGraph
              ? "border-warning text-warning"
              : "border-line text-fog hover:text-snow")
          }
        >
          {showFullGraph ? "Full graph: on" : "Show full graph"}
        </button>
      </div>

      {!hasFocus && (
        <div className="card p-8 text-center text-fog text-sm font-mono">
          Select a file — from the Reading list, the Architecture map, or a Dependency Cluster — to explore what it
          depends on and what depends on it.
        </div>
      )}

      {hasFocus && (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-fog">
            {!showFullGraph && (
              <span>
                Focus: <span className="text-accent">{focusLabel}</span>
              </span>
            )}
            <span>
              {scope.nodeIds.length} of {nodes.length} files
              {scope.truncated && (
                <span className="text-warning"> · capped from {scope.totalNodesBeforeCap}</span>
              )}
            </span>
            <span>{scope.edges.length} edges</span>
            {scope.cycleEdgeKeys.size > 0 && (
              <span className="text-danger">{scope.cycleEdgeKeys.size} in cycles</span>
            )}
            <span className="text-fog/70">click folder = expand · click file = select · double-click = re-center</span>
          </div>

          {showFullGraph && (
            <p className="font-mono text-[10px] text-warning leading-relaxed">
              Full graph: every file at once, folders collapsed
              {scope.nodeIds.length > MAX_NODES_ADVISORY && (
                <> — {scope.nodeIds.length} nodes, past the {MAX_NODES_ADVISORY} this layout stays readable at</>
              )}
              . This is the shape the H5 postmortem found unreadable past a few dozen nodes; it is here for
              completeness, not as a way to read the codebase. Turn it off and pick a focus to get an answerable
              question back.
            </p>
          )}

          {scope.truncated && !showFullGraph && (
            <p className="font-mono text-[10px] text-warning">
              Showing the {DEFAULT_MAX_NODES} nearest of {scope.totalNodesBeforeCap} files in range — farthest hops
              dropped first. Reduce hops, or narrow by cluster, to see a complete neighbourhood rather than a capped one.
            </p>
          )}

          {dirsAvailable.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-fog">Folders</span>
              {dirsAvailable.slice(0, 12).map((d) => (
                <button
                  key={d.dir}
                  onClick={() =>
                    setExpandedDirs((prev) => {
                      const next = new Set(prev);
                      if (next.has(d.dir)) next.delete(d.dir); else next.add(d.dir);
                      return next;
                    })
                  }
                  className={
                    "font-mono text-[10px] rounded-full px-2.5 py-1 border transition-colors " +
                    (expandedDirs.has(d.dir)
                      ? "border-accent/50 text-accent"
                      : "border-line text-fog hover:text-snow")
                  }
                  title={`${d.dir} — ${d.fileCount} files in scope`}
                >
                  {d.dir} ×{d.fileCount}
                </button>
              ))}
            </div>
          )}

          <div
            ref={setContainer}
            className="w-full rounded-lg border border-line bg-ink"
            style={{ height: 620 }}
          />

          <div className="flex flex-wrap items-center gap-4 font-mono text-[9px] uppercase tracking-widest text-fog">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5" style={{ background: COLOR.cycle }} /> cycle edge
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm border-2"
                style={{ borderColor: COLOR.focus }}
              />{" "}
              focus
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-sm border border-dashed" style={{ borderColor: COLOR.textDim }} />{" "}
              expanded folder
            </span>
            <span>×N on an edge = that many file-to-file imports collapsed into one</span>
          </div>
        </>
      )}
    </div>
  );
}
