/** Phase 8 checkpoint 3b-2 -- the Context view's graph.
 *
 *  DRAWS ONLY. Every structural decision (tray split, folder collapse, the
 *  subsystem vote, which side a "both" file lands on) is made in
 *  lib/contextLayout.ts, because vitest here is environment:node and there are
 *  no component tests -- logic left in this file is logic nothing verifies.
 *
 *  NO TOKEN NUMBERS. That is ck4, and the ck3a-quater envelope (0.92-1.09 across
 *  five files) means the label needs a decision this checkpoint does not make.
 *
 *  RECONCILIATION IS ON SCREEN, not inferable. The header states
 *  134 + 124 = 258 and 22 + 258 - 6 = 274 explicitly, because two trays that
 *  each look complete and sum to less than the badge is §17.25 moved into
 *  layout (D22).
 */
import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";

import { buildContextGraph, ContextGraphInputT } from "../lib/contextGraph";
import { buildContextLayout, GroupT, reconcile, TrayT } from "../lib/contextLayout";
import { actionForNode } from "../lib/contextNav";
import { LayoutTargetT, RunElkLayoutDepsT, runElkLayout } from "../lib/elkLayoutRun";
import { computeElkLayout } from "../lib/elkWorkerLayout";

/** Subsystem -> colour. Six values on 2256, twelve on 2419, so a small fixed
 *  palette is enough and a generated one would be less legible. Index is by
 *  order of first appearance, so the dominant subsystem is always palette[0]. */
const PALETTE = [
  "#4f46a8", "#0e7c86", "#a8620e", "#7d1f6b", "#2b6b3f", "#8a1f2f",
  "#3d5a99", "#6b6b1f", "#1f6b6b", "#993d7a", "#4a7d1f", "#7a4a1f",
];
/** D15/null path: a subsystem we could not determine is GREY, and grey is not
 *  in the palette -- so "unclustered" can never be confused with a cluster.
 *  UNVERIFIED ON DATA: repo 6 is 100% covered, so this colour has never been
 *  rendered from a real payload. See contextLayout.test.ts. */
const UNCLUSTERED = "#8b8b9a";

/** Tray accents. The same three colours label the counts and tint the tray
 *  cards, so "62 imported by" is findable without reading the caption. Chosen
 *  to sit apart from the subsystem palette, which colours the NODES -- these
 *  colour the DIRECTION, and the two must not be confused. */
const TRAY_TONE: Record<string, { fg: string; bg: string; line: string }> = {
  imports:  { fg: "#0e7c86", bg: "rgba(14,124,134,.12)",  line: "rgba(14,124,134,.45)" },
  source:   { fg: "#4f46a8", bg: "rgba(79,70,168,.14)",   line: "rgba(79,70,168,.45)" },
  tests:    { fg: "#a8620e", bg: "rgba(168,98,14,.12)",   line: "rgba(168,98,14,.45)" },
};

function colourFor(sid: number | null, order: Map<number, number>): string {
  if (sid === null) return UNCLUSTERED;
  const i = order.get(sid);
  return i === undefined ? UNCLUSTERED : PALETTE[i % PALETTE.length];
}

interface Props {
  envelope: ContextGraphInputT;
  /** Navigate to another file. The parent owns the URL (and the fingerprint),
   *  so this component never builds a link itself. */
  onNavigate: (fileId: number, path: string) => void;
}

export default function NeighborhoodView({ envelope, onNavigate }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [cy, setCy] = useState<cytoscape.Core | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  /** A collapsed group the user clicked. Its files are listed below the graph
   *  rather than expanded into it: `unit_tests` holds 76, and re-laying-out 76
   *  nodes in a container sized for ~20 is the §17.37 legibility defect again. */
  const [drilled, setDrilled] = useState<{ key: string; ids: number[] } | null>(null);
  /** Height that actually fits the viewport.
   *
   *  A fixed `calc(100vh - Npx)` has to GUESS how tall the repo header and tab
   *  strip are, and it guessed low -- the graph ran off the bottom of the
   *  screen, which is the thing this layout was meant to stop. Measured from the
   *  panel's own offsetTop instead, and re-measured on resize. */
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [panelH, setPanelH] = useState(560);
  useEffect(() => {
    const measure = () => {
      const top = panelRef.current?.getBoundingClientRect().top ?? 0;
      setPanelH(Math.max(420, window.innerHeight - top - 24));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const { layout, recon, subsystemOrder } = useMemo(() => {
    const graph = buildContextGraph(envelope);
    const subsystemOf = new Map(
      envelope.connected_index.map((e) => [e.id, e.subsystem_modularity_id]));
    const l = buildContextLayout(graph, subsystemOf);
    // Order by frequency so the dominant subsystem gets palette[0].
    const freq = new Map<number, number>();
    for (const e of envelope.connected_index) {
      if (e.subsystem_modularity_id === null) continue;
      freq.set(e.subsystem_modularity_id, (freq.get(e.subsystem_modularity_id) ?? 0) + 1);
    }
    const order = new Map(
      [...freq.entries()].sort((a, b) => b[1] - a[1]).map(([sid], i) => [sid, i]));
    return { layout: l, recon: reconcile(l), subsystemOrder: order };
  }, [envelope]);

  const pathById = useMemo(
    () => new Map(envelope.connected_index.map((e) => [e.id, e.path])),
    [envelope.connected_index]);

  const elements = useMemo(() => {
    const nodes: cytoscape.ElementDefinition[] = [{
      data: {
        id: "centre", label: envelope.path.split("/").pop() ?? envelope.path,
        kind: "centre", fileCount: 1, colour: "#1a1a2e", full: envelope.path,
      },
    }];
    const edges: cytoscape.ElementDefinition[] = [];

    for (const tray of layout.trays) {
      const push = (key: string, g: GroupT | null, label: string,
                    fileCount: number, isAgg: boolean) => {
        const id = `${tray.id}:${key}`;
        nodes.push({
          data: {
            id, label, kind: isAgg ? "aggregate" : (fileCount > 1 ? "folder" : "file"),
            fileCount,
            colour: isAgg ? UNCLUSTERED : colourFor(g?.subsystemId ?? null, subsystemOrder),
            mixed: g?.mixed ?? false,
            tray: tray.id,
            // D16: a group containing a both-direction file is marked.
            hasBoth: g ? g.fileIds.some((fid) => layout.bothIds.has(fid)) : false,
            full: key,
            // carried on the node so the click handler needs no lookup table
            ids: g ? g.fileIds : [],
          },
        });
        // Orientation is the real relation: imports flow out of the centre.
        if (tray.id === "imports") edges.push({ data: { id: `e-${id}`, source: "centre", target: id, cross: g?.subsystemId !== null && g?.mixed } });
        else edges.push({ data: { id: `e-${id}`, source: id, target: "centre", cross: g?.mixed ?? false } });
      };
      for (const g of tray.shown) {
        push(g.key, g, g.fileCount > 1 ? `${g.key.split("/").pop()} (${g.fileCount})` : (g.key.split("/").pop() ?? g.key), g.fileCount, false);
      }
      if (tray.aggregate) {
        push("__aggregate__", null,
          `${tray.aggregate.groupCount} more folders (${tray.aggregate.fileCount})`,
          tray.aggregate.fileCount, true);
      }
    }
    return [...nodes, ...edges];
  }, [envelope.path, layout, subsystemOrder]);

  useEffect(() => {
    if (!containerRef.current) return;
    const instance = cytoscape({
      container: containerRef.current,
      elements: [],
      // THE SCROLL TRAP, FIXED. cytoscape grabs the wheel by default and zooms,
      // so a page scroll dies the moment the cursor crosses the graph and the
      // only way past is the scrollbar. Wheel now belongs to the PAGE; zoom is
      // on explicit controls. Drag-to-pan still works, which is the interaction
      // people actually reach for inside a graph.
      userZoomingEnabled: false,
      autoungrabify: true,
      style: [
        { selector: "node", style: {
          label: "data(label)", "font-size": 12, "text-valign": "center",
          "text-halign": "center", "background-color": "data(colour)",
          color: "#fff", "text-outline-width": 0, shape: "round-rectangle",
          width: "label", height: 28, padding: "8px", "text-wrap": "wrap",
          "text-max-width": "200px",
        } },
        { selector: 'node[kind="centre"]', style: {
          shape: "hexagon", height: 40, "font-size": 12, "font-weight": "bold",
          "border-width": 3, "border-color": "#4f46a8",
        } },
        { selector: 'node[kind="aggregate"]', style: {
          shape: "round-diamond", "border-width": 2, "border-style": "dashed",
          "border-color": "#4a4a5c",
        } },
        // D22: the test tray must be distinguishable IN THE GRAPH, not only in
        // the header. ELK stacks all importers in one column, so without this
        // the 124 test files are indistinguishable from the 134 source ones and
        // the split exists only as a sentence. Shape, not colour -- colour is
        // already spent on subsystem (D15).
        { selector: 'node[tray="tests"]', style: {
          shape: "cut-rectangle", "border-width": 2, "border-color": "#6b6b85",
          "border-style": "dotted",
        } },
        { selector: "node[?mixed]", style: { "border-width": 2, "border-style": "dashed", "border-color": "#fff" } },
        { selector: "node[?hasBoth]", style: { "border-width": 3, "border-color": "#e8b23c" } },
        { selector: "edge", style: {
          width: 1, "line-color": "#c9c9dc", "target-arrow-color": "#c9c9dc",
          "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.7,
        } },
        { selector: "edge[?cross]", style: { width: 2, "line-color": "#a8620e", "target-arrow-color": "#a8620e" } },
      ],
    });
    setCy(instance);
    return () => { instance.destroy(); setCy(null); };
  }, []);

  // CLICK -> ACTION. The decision lives in lib/contextNav.ts so it is tested
  // headlessly; this only dispatches it.
  useEffect(() => {
    if (!cy) return;
    const handler = (evt: cytoscape.EventObject) => {
      const d = evt.target.data() as {
        kind: string; ids?: number[]; full?: string; fileCount: number;
      };
      const ids = d.ids ?? [];
      const action = actionForNode({
        kind: d.kind,
        fileIds: ids,
        groupKey: d.full ?? "",
        paths: ids.length === 1 ? [pathById.get(ids[0]) ?? ""] : [],
      });
      if (action.kind === "navigate") { setDrilled(null); onNavigate(action.fileId, action.path); }
      else if (action.kind === "drill") setDrilled({ key: action.groupKey, ids: action.fileIds });
      else setDrilled(null);
    };
    cy.on("tap", "node", handler);
    return () => { cy.removeListener("tap", "node", handler); };
  }, [cy, pathById, onNavigate]);

  useEffect(() => {
    if (!cy) return;
    cy.elements().remove();
    cy.add(elements);
    setLayoutError(null);
    // The cleanup React calls IS runElkLayout's cancel function, returned
    // unchanged. Pinned by contextNeighborhood.wiring.test.ts.
    return runElkLayout(
      cy as unknown as LayoutTargetT,
      {
        algorithm: "layered",
        // RIGHT so horizontal position encodes direction: importers left of the
        // centre, imports right of it.
        "elk.direction": "RIGHT",
        "elk.spacing.nodeNode": "14",
        "elk.layered.spacing.nodeNodeBetweenLayers": "260",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
        "elk.padding": "[top=24,left=24,bottom=24,right=24]",
      },
      {
        compute: computeElkLayout as unknown as RunElkLayoutDepsT["compute"],
        onSettled: () => undefined,
        onError: (err) => setLayoutError(String(err)),
      },
    );
  }, [cy, elements]);

  const zoomBy = (f: number) => { if (cy) cy.zoom({ level: cy.zoom() * f, renderedPosition: { x: (cy.width() / 2), y: (cy.height() / 2) } }); };
  const fit = () => { if (cy) cy.fit(undefined, 40); };

  const tray = (id: TrayT["id"]) => layout.trays.find((t) => t.id === id)!;
  const c = layout.counts;

  const trayCards = (["imports", "source", "tests"] as const).map((id) => {
    const tr = tray(id);
    const tone = TRAY_TONE[id];
    return (
      <div key={id} data-testid={`tray-${id}`}
           className="rounded-lg px-3 py-2"
           style={{ background: tone.bg, border: `1px solid ${tone.line}` }}>
        <div className="flex items-baseline gap-2">
          {/* The NUMBER first and large -- it is what the tray is for. */}
          <span className="font-mono text-xl font-bold leading-none"
                style={{ color: tone.fg }}>{tr.total}</span>
          <span className="text-[13px] font-medium">{tr.label}</span>
        </div>
        <div className="font-mono text-[10.5px] text-fog mt-1">
          {/* FILES vs FOLDERS. "10 ... all 3 shown" read as a contradiction --
              10 is the file count, 3 is how many folders they sit in. */}
          {tr.aggregate
            ? `in ${tr.shown.length + tr.aggregate.groupCount} folders · ${tr.shown.length} drawn, ${tr.aggregate.groupCount} folded (${tr.aggregate.fileCount} files)`
            : tr.total === 0 ? "none"
            : `in ${tr.shown.length} folder${tr.shown.length === 1 ? "" : "s"}, all drawn`}
        </div>
      </div>
    );
  });

  return (
    // TWO COLUMNS. The graph was taking the full width and pushing everything
    // else below the fold, so the trays, the drill list and the unresolved tray
    // were only reachable by scrolling past a 900px canvas that ate the wheel.
    // Now the graph holds a tall fixed panel on the left and every piece of TEXT
    // lives in its own scrollable rail on the right -- so the rail scrolls
    // independently and the page never has to.
    <div ref={panelRef} className="grid gap-3 items-start"
         style={{ gridTemplateColumns: "minmax(0,1fr) minmax(320px,26rem)" }}>

      {/* ---------- LEFT: the graph ---------- */}
      <div className="card relative overflow-hidden"
           style={{ height: panelH }}>
        {c.connected === 0 ? (
          <div className="h-full flex items-center justify-center p-8">
            <p className="text-sm text-ink-2 max-w-prose text-center"
               data-testid="ctx-no-neighbours">
              <strong>This file has no resolved connections.</strong> Nothing in the
              graph imports it and it imports nothing the resolver could pin, so the
              neighbourhood is the file itself — a real answer about the repository,
              not a missing one.
            </p>
          </div>
        ) : (
          <>
            <div ref={containerRef} data-testid="ctx-graph" className="h-full w-full" />
            {/* Zoom lives here because the WHEEL no longer zooms -- see the
                cytoscape init. Drag still pans. */}
            <div className="absolute top-2 right-2 flex gap-1">
              {[["−", () => zoomBy(1 / 1.25)], ["+", () => zoomBy(1.25)]].map(([lbl, fn]) => (
                <button key={String(lbl)} onClick={fn as () => void}
                        className="w-7 h-7 rounded border font-mono text-sm leading-none"
                        style={{ background: "var(--surface, #1b1b28)", borderColor: "#41415a" }}>
                  {lbl as string}
                </button>
              ))}
              <button onClick={fit}
                      className="h-7 px-2 rounded border font-mono text-[11px]"
                      style={{ background: "var(--surface, #1b1b28)", borderColor: "#41415a" }}>
                fit
              </button>
            </div>
            <div className="absolute bottom-2 left-3 font-mono text-[10px] text-fog">
              drag to pan · use + / − to zoom · the wheel scrolls the page
            </div>
          </>
        )}
      </div>

      {/* ---------- RIGHT: everything readable, independently scrollable ---------- */}
      <div className="flex flex-col gap-3 overflow-y-auto pr-1"
           style={{ maxHeight: panelH }}>

        <div className="card p-4 space-y-3">
          <div>
            <h2 className="text-sm font-semibold">Context</h2>
            <p className="font-mono text-[11px] text-fog break-all mt-0.5">{envelope.path}</p>
          </div>

          <div data-testid="ctx-badge">
            {envelope.ratio_display === null ? (
              <p className="text-[13px] text-ink-2" data-testid="ctx-no-ratio">
                <strong>No saving figure for this file.</strong>{" "}
                {envelope.ratio_absent_reason}
              </p>
            ) : (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-3xl font-bold leading-none"
                        data-testid="ctx-badge-ratio">{envelope.ratio_display}</span>
                  <span className="text-[13px] text-ink-2">cheaper than reading
                    every connected file</span>
                </div>
                <p className="font-mono text-[10.5px] text-fog mt-1"
                   data-testid="ctx-badge-envelope">
                  estimate, {envelope.envelope_pct} against tiktoken on the five measured files
                </p>
              </>
            )}
            <p className="font-mono text-[11px] text-fog mt-2" data-testid="ctx-badge-costs">
              {envelope.costs_line}
            </p>
          </div>
        </div>

        {/* The three counts, large and colour-coded to match nothing else on the
            page but each other -- direction, not subsystem. */}
        <div className="grid grid-cols-1 gap-2">{trayCards}</div>

        <div className="card p-3">
          <p className="font-mono text-[11px] leading-relaxed" data-testid="ctx-reconcile">
            <span className="text-fog">imports </span>
            <b>{c.imports + c.both}</b>
            <span className="text-fog"> + imported by </span><b>{c.importers}</b>
            <span className="text-fog"> (</span><b>{c.source}</b>
            <span className="text-fog"> source + </span><b>{c.tests}</b>
            <span className="text-fog"> tests) − both </span><b>{c.both}</b>
            <span className="text-fog"> = </span>
            <b className="text-sm">{c.connected}</b>
            <span className="text-fog"> connected files</span>
            {recon.allOk() ? "" : "  ⚠ COUNTS DO NOT RECONCILE"}
          </p>
        </div>

        {c.connected > 0 && (
          <div className="card p-3 flex flex-col gap-1.5 font-mono text-[10px]
                          uppercase tracking-wider text-fog">
            <span>◆ dashed = several folders folded together</span>
            <span style={{ color: "#e8b23c" }}>▢ gold border = imports AND is imported by</span>
            <span style={{ color: "#a8620e" }}>— orange edge = crosses subsystems</span>
            <span style={{ color: UNCLUSTERED }}>▢ grey = subsystem unknown</span>
          </div>
        )}

        {layoutError && <p className="card p-3 text-xs">Layout failed: {layoutError}</p>}

        {drilled && (
          <div className="card p-3 space-y-2" data-testid="ctx-drill">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-xs font-semibold break-all">
                {drilled.key} — {drilled.ids.length} file{drilled.ids.length === 1 ? "" : "s"}
              </h3>
              <button className="font-mono text-[10px] underline text-fog shrink-0"
                      onClick={() => setDrilled(null)}>close</button>
            </div>
            <div className="flex flex-col gap-0.5">
              {drilled.ids.map((fid) => (
                <button key={fid} data-testid="ctx-drill-item"
                        className="font-mono text-[11px] text-left underline decoration-dotted break-all"
                        onClick={() => { const pth = pathById.get(fid) ?? ""; setDrilled(null); onNavigate(fid, pth); }}>
                  {pathById.get(fid)}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* D17: not files, so not the file grammar -- their own tray, and now it
            sits IN the readable rail instead of below a full-height canvas. */}
        <div className="card p-3 space-y-2" data-testid="ctx-unresolved">
          <h3 className="text-xs font-semibold">
            Unresolved imports ({layout.unresolved.length})
          </h3>
          <p className="font-mono text-[10px] text-fog">
            not files — stdlib or third-party specifiers the resolver could not pin
          </p>
          <div className="flex flex-wrap gap-1">
            {layout.unresolved.map((u, i) => (
              <span key={`${u.raw_specifier}-${u.line_number}-${i}`}
                    className="font-mono text-[10px] px-1.5 py-0.5 rounded border"
                    style={{ borderColor: "#c9c9dc", color: "#6b6b85" }}
                    title={`line ${u.line_number} · ${u.kind}`}>
                {u.raw_specifier}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
