import { useMemo, useRef, useState } from "react";
import { DirEdgeT, DirKindT, DirNodeT } from "../lib/api";
import {
  buildRenderNodes, computeLayeredLayout, dirnameOfPath, RenderNode,
} from "../lib/layeredLayout";

interface FileRef {
  file_id: number;
  path: string;
}
// Phase H3: same six-ish token reuse as G4's GraphView / MermaidPanel --
// canvas/SVG fill and stroke attributes need literal CSS colors, not
// Tailwind classes, so there's no way to hand either a class name
// instead. Five kinds here (H1's dir_aggregation.py), not file-level's
// six -- "tooling" replaces "barrel"/"config"/"generated" at directory
// granularity.
export const KIND_COLOR: Record<DirKindT, string> = {
  entry: "#3DDC97", // accent
  tooling: "#E0B450", // warning
  test: "#4FC7D4", // info
  migration: "#E2646E", // danger
  source: "#E9F1EE99", // snow, translucent -- the common case, meant to recede
};
const KIND_LABEL: Record<DirKindT, string> = {
  entry: "Entry", source: "Source", test: "Tests", tooling: "Tooling", migration: "Migrations",
};
const ALL_KINDS: DirKindT[] = ["entry", "source", "test", "tooling", "migration"];

// Phase I2: a categorical palette for coloring by dependency cluster
// instead of by kind -- same "canvas/SVG needs literal color strings"
// exception as KIND_COLOR above. Cluster count varies per repo (4 on this
// one, 9 on the ESLint validation repo) and isn't bounded the way the 5
// kinds are, so this cycles via modulo past 10 clusters -- a known,
// stated limit (colors repeat), not a silent one.
const CLUSTER_PALETTE = [
  "#3DDC97", "#4FC7D4", "#E0B450", "#D4739B", "#9B87F5",
  "#F2A65A", "#6EC6C1", "#B5D96C", "#E2646E", "#7FA8D9",
];
const NO_CLUSTER_COLOR = "#E9F1EE33"; // no cluster data at all -- neutral, recedes
// Below this, a box's dominant cluster covers less than 3/4 of its files
// -- same threshold and reasoning as CYCLE_COHERENCE_WEAK_THRESHOLD on
// the backend (subsystems.py): a real split, not a rendering artifact,
// worth surfacing rather than painting the whole box one clean color.
// Exported so MatrixView.tsx applies the identical threshold.
export const CLUSTER_PURITY_WEAK_THRESHOLD = 0.75;

// Exported so MatrixView.tsx uses the exact same cluster->color mapping --
// one source of truth, same reasoning as lib/neighborGrouping.ts being
// shared between Focus and Mermaid, so the two views can never disagree
// about which color a given cluster id is.
export function clusterColor(clusterId: number | null): string {
  if (clusterId === null) return NO_CLUSTER_COLOR;
  return CLUSTER_PALETTE[clusterId % CLUSTER_PALETTE.length];
}

function isImpureCluster(n: RenderNode): boolean {
  return n.clusterPurity !== null && n.clusterPurity < CLUSTER_PURITY_WEAK_THRESHOLD;
}

const COLLAPSED_H = 32;
const CYCLE_COLLAPSED_H = 46;
const COLUMN_W = 190;
const MARGIN_X = 100;
const ROW_GAP = 14;
const REGION_GAP = 36;
const REGION_TOP = 40;
const REGION_LABEL_H = 26;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3.2;
// Semantic zoom, per the reference mockup: three explicit tiers, not a
// continuous blend -- shapes only below 0.72x (just position/kind/size
// still legible), labels between 0.72x and 1.45x, file names past 1.45x.
const TIER_1_MIN = 0.72;
const TIER_2_MIN = 1.45;
const TIER_LABELS = ["DETAIL: SHAPES", "DETAIL: LABELS", "DETAIL: FILES"];
// Hover isolation fades context, never hides it -- the specific thing
// the old force view's dimming got wrong (G4 postmortem, Phase H brief).
const DIM_OPACITY = 0.3;
const UNRELATED_EDGE_OPACITY = 0.07;

function tierOf(k: number): number {
  return k < TIER_1_MIN ? 0 : k < TIER_2_MIN ? 1 : 2;
}

interface Box {
  x: number; y: number; w: number; h: number; cx: number; cy: number;
}

function boxSize(node: RenderNode, expanded: boolean, tier: number): { w: number; h: number } {
  if (!expanded) {
    if (node.isCycle) return { w: 168, h: CYCLE_COLLAPSED_H };
    return { w: Math.max(112, node.label.length * 7.6 + 34), h: COLLAPSED_H };
  }
  const cols = Math.min(5, node.fileCount);
  const rows = Math.ceil(node.fileCount / cols);
  const cw = tier === 2 ? 78 : 24;
  const w = Math.max(cols * cw + 26, node.isCycle ? 168 : 132);
  const h = rows * (tier === 2 ? 20 : 22) + (node.isCycle ? 58 : 44);
  return { w, h };
}

// Column-stacking layout: each (region, layer) pair is an independent
// vertical column. Expanding a node only grows ITS box and pushes
// later-in-column siblings down -- never sideways, never into another
// column. This is the property the whole deterministic-layout design
// exists for: an expand not a wall-clock cause of "did the diagram move,
// where did that box go."
function layoutBoxes(
  renderNodes: RenderNode[], expanded: Set<string>, tier: number, regionOrder: string[],
): Map<string, Box> {
  const columns = new Map<string, RenderNode[]>();
  for (const n of renderNodes) {
    const key = `${n.region}|${n.layer}`;
    if (!columns.has(key)) columns.set(key, []);
    columns.get(key)!.push(n);
  }
  for (const group of columns.values()) group.sort((a, b) => a.order - b.order);

  // region vertical band: tall enough for its tallest column, stacked
  // top to bottom in a stable order.
  const regionTop = new Map<string, number>();
  let cursor = REGION_TOP;
  for (const region of regionOrder) {
    regionTop.set(region, cursor);
    const heights = [...columns.entries()]
      .filter(([key]) => key.startsWith(`${region}|`))
      .map(([, group]) => group.reduce((sum, n) => sum + boxSize(n, expanded.has(n.id), tier).h + ROW_GAP, 0));
    const bandHeight = Math.max(80, ...heights, 0);
    cursor += REGION_LABEL_H + bandHeight + REGION_GAP;
  }

  const positions = new Map<string, Box>();
  for (const [key, group] of columns) {
    const [region, layerStr] = key.split("|");
    const layer = Number(layerStr);
    const x = MARGIN_X + layer * COLUMN_W;
    let y = (regionTop.get(region) ?? REGION_TOP) + REGION_LABEL_H;
    for (const n of group) {
      const { w, h } = boxSize(n, expanded.has(n.id), tier);
      positions.set(n.id, { x: x - w / 2, y, w, h, cx: x, cy: y + h / 2 });
      y += h + ROW_GAP;
    }
  }
  return positions;
}

function anchorPoint(b: Box, other: Box): { x: number; y: number } {
  const dx = other.cx - b.cx;
  const dy = other.cy - b.cy;
  const hw = b.w / 2 + 5;
  const hh = b.h / 2 + 5;
  const s = Math.min(dx !== 0 ? hw / Math.abs(dx) : 1e9, dy !== 0 ? hh / Math.abs(dy) : 1e9);
  return { x: b.cx + dx * s, y: b.cy + dy * s };
}

export function ArchitectureMap({
  nodes, edges, files, selectedFileId, onSelectFile, pairFilter, onClearPairFilter, onSelectDir,
  colorMode, onColorModeChange, clusterLabelById,
}: {
  nodes: DirNodeT[];
  edges: DirEdgeT[];
  files: FileRef[];
  selectedFileId: number | null;
  // Phase I2: shared with MatrixView via RepoDetail so switching tabs
  // keeps the same coloring active, same pattern as the algorithm toggle
  // on the Dependency Clusters tab.
  colorMode: "kind" | "cluster";
  onColorModeChange: (mode: "kind" | "cluster") => void;
  clusterLabelById: Map<number, string>;
  // Sets shared selection state; the caller (RepoDetail) also switches
  // the active view to Focus -- "clicking a file dot goes to the focus
  // view" per the brief. Deferred until H4 built Focus to consume it;
  // this component only ever sets state, never navigates itself.
  onSelectFile: (fileId: number) => void;
  // Phase H4: "clicking a [matrix] cell filters the architecture map to
  // that pair" -- a pair of raw (uncondensed) directory ids from the
  // Matrix tab, which this component maps onto whichever render node
  // (possibly a merged cycle group) each one actually belongs to. Pinned
  // until cleared (clicking empty canvas space), same mechanism as hover
  // isolation but not tied to mouse position.
  pairFilter?: [string, string] | null;
  onClearPairFilter?: () => void;
  // Phase H5: feeds the shared, persistent DetailPanel (RepoDetail owns
  // it, not this component) -- always a RAW directory id, never a merged
  // render-node id like "scc:2". For a cycle group, that's the first
  // member; the panel shows one directory's stats either way, and the
  // Matrix tab is where both members' numbers live side by side.
  onSelectDir?: (dirId: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [activeKinds, setActiveKinds] = useState<Set<DirKindT>>(new Set(ALL_KINDS));
  const [coreOnly, setCoreOnly] = useState(false);
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  const layout = useMemo(() => computeLayeredLayout(nodes, edges), [nodes, edges]);
  const { renderNodes, renderEdges } = useMemo(
    () => buildRenderNodes(nodes, edges, layout), [nodes, edges, layout],
  );
  const byId = useMemo(() => new Map(renderNodes.map((n) => [n.id, n])), [renderNodes]);

  const renderIdForDir = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of renderNodes) for (const memberId of n.memberIds) m.set(memberId, n.id);
    return m;
  }, [renderNodes]);
  const pairRenderIds = useMemo(() => {
    if (!pairFilter) return null;
    const [a, b] = pairFilter;
    return new Set([renderIdForDir.get(a) ?? a, renderIdForDir.get(b) ?? b]);
  }, [pairFilter, renderIdForDir]);

  // Directory-level aggregation carries counts, not file lists -- expansion
  // shows real files by grouping the already-loaded Reading-list data
  // client-side, the same dirname rule dir_aggregation.py uses server-side.
  const filesByDir = useMemo(() => {
    const map = new Map<string, FileRef[]>();
    for (const f of files) {
      const dir = dirnameOfPath(f.path);
      if (!map.has(dir)) map.set(dir, []);
      map.get(dir)!.push(f);
    }
    return map;
  }, [files]);

  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of renderEdges) {
      d.set(e.source, (d.get(e.source) ?? 0) + 1);
      d.set(e.target, (d.get(e.target) ?? 0) + 1);
    }
    return d;
  }, [renderEdges]);

  const isVisible = (n: RenderNode) =>
    activeKinds.has(n.kind) && (!coreOnly || n.kind === "entry" || (degree.get(n.id) ?? 0) >= 3);

  const visibleNodes = renderNodes.filter(isVisible);
  const tier = tierOf(transform.k);

  const grounded = visibleNodes.filter((n) => !n.isolated);
  const satellites = visibleNodes.filter((n) => n.isolated);
  const regionOrder = useMemo(
    () => [...new Set(grounded.map((n) => n.region))].sort(),
    [grounded],
  );
  const boxes = useMemo(
    () => layoutBoxes(grounded, expanded, tier, regionOrder),
    [grounded, expanded, tier, regionOrder],
  );

  // Satellites sit in their own row, clearly above every grounded region,
  // spread across the grounded content's actual x-range with a slight bow
  // for the reference's "arc" character. Found live: an earlier version
  // used a circular arc centered ON the grounded content with a radius
  // proportional to its width -- correct arc math, wrong parameters, and
  // for a graph wide enough (this repo's real 18-node layout) the arc
  // swept back into the rightmost column and sat directly on top of it.
  // A dedicated band strictly above minY, independent of graph width,
  // can't overlap grounded content at any size.
  const satellitePositions = useMemo(() => {
    const allBoxes = [...boxes.values()];
    const minX = allBoxes.length ? Math.min(...allBoxes.map((b) => b.x)) : 0;
    const maxX = allBoxes.length ? Math.max(...allBoxes.map((b) => b.x + b.w)) : 400;
    const minY = allBoxes.length ? Math.min(...allBoxes.map((b) => b.y)) : 0;
    const positions = new Map<string, { x: number; y: number }>();
    const n = satellites.length;
    const bandY = minY - 60;
    satellites.forEach((sat, i) => {
      const x = n === 1 ? (minX + maxX) / 2 : minX + ((maxX - minX) / (n - 1)) * i;
      const bow = n > 1 ? Math.sin((i / (n - 1)) * Math.PI) * 20 : 0;
      positions.set(sat.id, { x, y: bandY - bow });
    });
    return positions;
  }, [satellites, boxes]);

  for (const n of satellites) {
    const p = satellitePositions.get(n.id);
    if (p) boxes.set(n.id, { x: p.x - 60, y: p.y - 15, w: 120, h: 30, cx: p.x, cy: p.y });
  }

  const bounds = useMemo(() => {
    const all = [...boxes.values()];
    if (all.length === 0) return { minX: 0, minY: 0, maxX: 800, maxY: 600 };
    return {
      minX: Math.min(...all.map((b) => b.x)) - 40,
      minY: Math.min(...all.map((b) => b.y)) - 40,
      maxX: Math.max(...all.map((b) => b.x + b.w)) + 40,
      maxY: Math.max(...all.map((b) => b.y + b.h)) + 40,
    };
  }, [boxes]);
  const viewW = Math.max(600, bounds.maxX - bounds.minX);
  const viewH = Math.max(400, bounds.maxY - bounds.minY);

  const maxWeight = Math.max(1, ...renderEdges.map((e) => e.weight));

  function zoom(factor: number, px?: number, py?: number) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, transform.k * factor));
    const scaleX = viewW / rect.width;
    const scaleY = viewH / rect.height;
    const X = ((px ?? rect.width / 2) * scaleX) + bounds.minX;
    const Y = ((py ?? rect.height / 2) * scaleY) + bounds.minY;
    const newX = X - ((X - transform.x) / transform.k) * k;
    const newY = Y - ((Y - transform.y) / transform.k) * k;
    setTransform({ k, x: newX, y: newY });
  }

  function handleWheel(e: React.WheelEvent<SVGSVGElement>) {
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    zoom(e.deltaY < 0 ? 1.13 : 1 / 1.13, e.clientX - rect.left, e.clientY - rect.top);
  }
  function handleMouseDown(e: React.MouseEvent<SVGSVGElement>) {
    dragRef.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
  }
  function handleMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!dragRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const scaleX = viewW / rect.width;
    const scaleY = viewH / rect.height;
    setTransform((t) => ({
      ...t,
      x: dragRef.current!.tx + (e.clientX - dragRef.current!.x) * scaleX,
      y: dragRef.current!.ty + (e.clientY - dragRef.current!.y) * scaleY,
    }));
  }
  function handleMouseUp() {
    dragRef.current = null;
  }

  function toggleKind(k: DirKindT | "__all") {
    setActiveKinds((prev) => {
      if (k === "__all") return prev.size === ALL_KINDS.length ? new Set(["entry", "source"]) : new Set(ALL_KINDS);
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next.size === 0 ? new Set(ALL_KINDS) : next;
    });
  }

  function toggleFullscreen() {
    const stage = stageRef.current;
    if (!stage) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
      setFullscreen(false);
    } else if (stage.requestFullscreen) {
      stage.requestFullscreen();
      setFullscreen(true);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded border border-line p-0.5 gap-0.5">
          {(["kind", "cluster"] as const).map((m) => (
            <button
              key={m}
              onClick={() => onColorModeChange(m)}
              className={
                "font-mono text-[9px] uppercase tracking-widest rounded px-2 py-1 transition-colors " +
                (colorMode === m ? "bg-accent/15 text-accent" : "text-fog hover:text-snow")
              }
            >
              {m}
            </button>
          ))}
        </div>
        <button
          onClick={() => toggleKind("__all")}
          className={
            "font-mono text-[10px] rounded-full px-2.5 py-1.5 border transition-colors " +
            (activeKinds.size === ALL_KINDS.length ? "border-fog/40 text-snow bg-glass" : "border-line text-fog")
          }
        >
          All <span className="text-fog">{renderNodes.length}</span>
        </button>
        {ALL_KINDS.filter((k) => renderNodes.some((n) => n.kind === k)).map((k) => (
          <button
            key={k}
            onClick={() => toggleKind(k)}
            className={
              "font-mono text-[10px] rounded-full px-2.5 py-1.5 border flex items-center gap-1.5 transition-colors " +
              (activeKinds.has(k) ? "border-line text-snow bg-glass" : "border-line/50 text-fog")
            }
          >
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: KIND_COLOR[k] }} />
            {KIND_LABEL[k]} <span className="text-fog">{renderNodes.filter((n) => n.kind === k).length}</span>
          </button>
        ))}
        <span className="flex-1" />
        <span className="font-mono text-[9px] text-fog tracking-wide">
          {visibleNodes.length} SHOWN · EDGE WIDTH = IMPORT COUNT · LEFT→RIGHT = DEPENDS ON
        </span>
      </div>

      {/* Phase I2: kind filtering above stays active regardless of color
          mode -- this row is purely informational, showing which color
          maps to which dependency cluster when colorMode="cluster". Not
          a second filter mechanism, to keep this a small, scoped
          addition rather than a parallel activeClusters filter state. */}
      {colorMode === "cluster" && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[9px] text-fog tracking-wide uppercase">Clusters:</span>
          {[...new Set(renderNodes.map((n) => n.clusterId).filter((id): id is number => id !== null))]
            .sort((a, b) => a - b)
            .map((id) => (
              <span
                key={id}
                className="font-mono text-[10px] rounded-full px-2.5 py-1 border border-line/50 text-fog flex items-center gap-1.5"
              >
                <span className="inline-block w-2 h-2 rounded-full" style={{ background: clusterColor(id) }} />
                {clusterLabelById.get(id) ?? `Cluster ${id}`}
              </span>
            ))}
          <span className="font-mono text-[9px] text-fog/70 tracking-wide">
            DASHED ACCENT = LESS THAN {Math.round(CLUSTER_PURITY_WEAK_THRESHOLD * 100)}% OF FILES SHARE THE DOMINANT CLUSTER
          </span>
        </div>
      )}

      <div
        ref={stageRef}
        className={"relative border border-line rounded overflow-hidden bg-ink " + (fullscreen ? "" : "")}
        style={{ height: 560 }}
      >
        <div className="absolute left-3 top-3 z-10 font-mono text-[10px] text-fog tracking-wide">
          {pairRenderIds && (
            <>
              FILTERED TO PAIR{" "}
              <button className="text-accent underline ml-1" onClick={() => onClearPairFilter?.()}>
                clear
              </button>
              {expanded.size > 0 && <span className="mx-2 text-line">·</span>}
            </>
          )}
          {expanded.size > 0 && (
            <>
              <b className="text-fog-2">{expanded.size}</b> EXPANDED{" "}
              <button className="text-accent underline ml-1" onClick={() => setExpanded(new Set())}>
                collapse all
              </button>
            </>
          )}
        </div>
        <div className="absolute right-3 top-3 z-10 font-mono text-[9.5px] text-fog tracking-wide">
          {TIER_LABELS[tier]}
        </div>

        <svg
          ref={svgRef}
          viewBox={`0 0 ${viewW} ${viewH}`}
          className="w-full h-full block cursor-grab active:cursor-grabbing"
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onClick={() => {
            setSelected(null);
            onClearPairFilter?.();
          }}
        >
          <defs>
            <marker id="arch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M2 2L8 5L2 8" fill="none" stroke="rgba(233,241,238,.45)" strokeWidth="1.4" strokeLinecap="round" />
            </marker>
            <marker id="arch-arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.5" markerHeight="5.5" orient="auto">
              <path d="M2 2L8 5L2 8" fill="none" stroke="#3DDC97" strokeWidth="1.6" strokeLinecap="round" />
            </marker>
          </defs>
          <g transform={`translate(${-bounds.minX * transform.k + transform.x}, ${-bounds.minY * transform.k + transform.y}) scale(${transform.k})`}>
            {regionOrder.map((region) => {
              const cols = [...boxes.entries()].filter(([id]) => byId.get(id)?.region === region && !byId.get(id)?.isolated);
              if (cols.length === 0) return null;
              const xs = cols.map(([, b]) => b);
              const rx = Math.min(...xs.map((b) => b.x)) - 30;
              const ry = Math.min(...xs.map((b) => b.y)) - REGION_LABEL_H;
              const rw = Math.max(...xs.map((b) => b.x + b.w)) - rx + 30;
              const rh = Math.max(...xs.map((b) => b.y + b.h)) - ry + 14;
              return (
                <g key={region}>
                  <rect x={rx} y={ry} width={rw} height={rh} rx={16} fill="none" stroke="var(--line, rgba(255,255,255,.09))" strokeWidth={0.6} strokeDasharray="5 5" />
                  <text x={rx + 14} y={ry + 18} fill="rgba(233,241,238,.44)" fontFamily="var(--mono)" fontSize={9.5} letterSpacing={1.5} className="font-mono uppercase">
                    {region === "(root)" ? "(ROOT)" : region.toUpperCase()}
                  </text>
                </g>
              );
            })}

            {renderEdges.map((e) => {
              const a = boxes.get(e.source);
              const b = boxes.get(e.target);
              if (!a || !b) return null;
              const p1 = anchorPoint(a, b);
              const p2 = anchorPoint(b, a);
              const len = Math.hypot(p2.x - p1.x, p2.y - p1.y);
              const focused = hovered != null
                ? (hovered === e.source || hovered === e.target)
                : pairRenderIds
                  ? (pairRenderIds.has(e.source) && pairRenderIds.has(e.target))
                  : false;
              const active = (hovered == null && pairRenderIds == null) || focused;
              const highlighted = hovered != null ? focused : (pairRenderIds != null && focused);
              const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 - Math.min(42, len * 0.13) };
              return (
                <g key={`${e.source}->${e.target}`}>
                  <path
                    d={`M${p1.x} ${p1.y} Q${mid.x} ${mid.y} ${p2.x} ${p2.y}`}
                    fill="none"
                    stroke={highlighted ? "var(--accent, #3DDC97)" : "rgba(233,241,238,.5)"}
                    strokeWidth={0.8 + (e.weight / maxWeight) * 3.4}
                    opacity={active ? (highlighted ? 0.75 : 0.46 - Math.min(0.2, len / 3400)) : UNRELATED_EDGE_OPACITY}
                    markerEnd={active ? (highlighted ? "url(#arch-arrow-hot)" : "url(#arch-arrow)") : undefined}
                  />
                  {highlighted && (
                    <text x={mid.x} y={mid.y - 4} fill="#3DDC97" fontFamily="var(--mono)" fontSize={9} textAnchor="middle">
                      {e.count}
                    </text>
                  )}
                </g>
              );
            })}

            {visibleNodes.map((n) => {
              const b = boxes.get(n.id);
              if (!b) return null;
              const isOpen = expanded.has(n.id);
              const linked = hovered != null
                ? (hovered === n.id || renderEdges.some((e) => (e.source === hovered && e.target === n.id) || (e.target === hovered && e.source === n.id)))
                : pairRenderIds
                  ? pairRenderIds.has(n.id)
                  : true;
              const dim = !linked;
              return (
                <g
                  key={n.id}
                  opacity={dim ? DIM_OPACITY : 1}
                  style={{ cursor: "pointer" }}
                  onMouseEnter={() => setHovered(n.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(n.id)) next.delete(n.id); else next.add(n.id);
                      return next;
                    });
                    setSelected(n.id);
                    onSelectDir?.(n.memberIds[0]);
                  }}
                >
                  <rect
                    x={b.x} y={b.y} width={b.w} height={b.h} rx={9}
                    fill={selected === n.id ? "rgba(61,220,151,.15)" : "rgba(255,255,255,.07)"}
                    stroke={selected === n.id ? "#3DDC97" : "rgba(255,255,255,.18)"}
                    strokeWidth={selected === n.id ? 1.7 : 1}
                  />
                  {n.isCycle && (
                    <rect
                      x={b.x + 3.5} y={b.y + 3.5} width={b.w - 7} height={b.h - 7} rx={6}
                      fill="none" stroke="rgba(255,255,255,.18)" strokeWidth={0.8} strokeDasharray="3 3"
                    />
                  )}
                  {/* Phase I2: impure-cluster indicator is its OWN dashed
                      rect around just the accent bar, not the cycle
                      rect's whole-box dashed border above -- the two
                      facts (this is a cycle / this cluster is impure)
                      are independent and shouldn't visually collide. */}
                  {colorMode === "cluster" && isImpureCluster(n) && (
                    <rect
                      x={b.x + 0.5} y={b.y + 0.5} width={3.5} height={b.h - 1}
                      fill="none" stroke={clusterColor(n.clusterId)} strokeWidth={0.8} strokeDasharray="2 2"
                    />
                  )}
                  <rect
                    x={b.x} y={b.y} width={3.5} height={b.h} rx={2}
                    fill={colorMode === "kind" ? KIND_COLOR[n.kind] : clusterColor(n.clusterId)}
                    opacity={colorMode === "cluster" && isImpureCluster(n) ? 0.5 : 0.92}
                  />
                  {(tier > 0 || isOpen) && (
                    <>
                      <text
                        x={b.x + 13} y={isOpen ? b.y + (n.isCycle ? 20 : 19) : (n.isCycle ? b.cy - 6 : b.cy + 4)}
                        fill="#E9F1EE" fontFamily="var(--sans)" fontSize={n.isCycle ? 12 : 12.5} fontWeight={600}
                      >
                        {n.label}
                      </text>
                      {n.isCycle && (
                        <text
                          x={b.x + 13} y={(isOpen ? b.y + 20 : b.cy - 6) + 14}
                          fill="#E2646E" fontFamily="var(--mono)" fontSize={8.5} letterSpacing={0.9}
                        >
                          CYCLE GROUP · {n.memberIds.length} DIRS
                        </text>
                      )}
                      {/* Phase I2: only rendered for non-cycle, EXPANDED
                          boxes -- a collapsed box is COLLAPSED_H=32px, no
                          room for a second text line (the cycle sublabel
                          above only fits because cycle boxes collapse
                          taller, CYCLE_COLLAPSED_H=46). Collapsed impure
                          boxes still get the dashed accent bar as their
                          visual cue; the percentage appears on expand. */}
                      {!n.isCycle && isOpen && colorMode === "cluster" && isImpureCluster(n) && (
                        <text
                          x={b.x + 13} y={b.y + 19 + 13}
                          fill={clusterColor(n.clusterId)} fontFamily="var(--mono)" fontSize={8.5} letterSpacing={0.9}
                        >
                          MIXED · {Math.round((n.clusterPurity ?? 0) * 100)}% ONE CLUSTER
                        </text>
                      )}
                      <text
                        x={b.x + b.w - 11} y={isOpen ? b.y + (n.isCycle ? 20 : 19) : (n.isCycle ? b.cy - 6 : b.cy + 4)}
                        fill="rgba(233,241,238,.44)" fontFamily="var(--mono)" fontSize={9.5} textAnchor="end"
                      >
                        {isOpen ? "−" : n.fileCount}
                      </text>
                    </>
                  )}
                  {isOpen && (
                    <ExpandedFiles
                      node={n}
                      box={b}
                      tier={tier}
                      files={n.memberIds.flatMap((m) => filesByDir.get(m) ?? [])}
                      selectedFileId={selectedFileId}
                      onSelectFile={onSelectFile}
                    />
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        <div className="absolute left-3 bottom-3 z-10 flex items-center gap-1.5">
          <button onClick={() => zoom(1 / 1.22)} className="w-7 h-7 border border-line rounded bg-ink/85 text-fog hover:bg-glass-2 hover:text-snow font-mono text-xs">−</button>
          <button onClick={() => zoom(1.22)} className="w-7 h-7 border border-line rounded bg-ink/85 text-fog hover:bg-glass-2 hover:text-snow font-mono text-xs">+</button>
          <button onClick={() => setTransform({ k: 1, x: 0, y: 0 })} className="h-7 px-2.5 border border-line rounded bg-ink/85 text-fog hover:bg-glass-2 hover:text-snow font-mono text-[9.5px] tracking-wide">RESET</button>
          <span className="font-mono text-[9.5px] text-fog pl-1">{Math.round(transform.k * 100)}%</span>
        </div>
        <div className="absolute right-3 bottom-3 z-10 flex items-center gap-1.5">
          <button
            onClick={() => setCoreOnly((v) => !v)}
            title="Core only — hide weakly connected"
            className={"w-7 h-7 border rounded font-mono text-xs " + (coreOnly ? "border-accent text-accent" : "border-line text-fog hover:bg-glass-2 hover:text-snow")}
          >
            ◉
          </button>
          <button onClick={toggleFullscreen} title="Fullscreen" className="w-7 h-7 border border-line rounded text-fog hover:bg-glass-2 hover:text-snow font-mono text-xs">⛶</button>
        </div>
      </div>
    </div>
  );
}

function ExpandedFiles({
  node, box, tier, files, selectedFileId, onSelectFile,
}: {
  node: RenderNode;
  box: Box;
  tier: number;
  files: FileRef[];
  selectedFileId: number | null;
  onSelectFile: (fileId: number) => void;
}) {
  const cols = Math.min(5, node.fileCount);
  const cw = tier === 2 ? 78 : 24;
  const rowH = tier === 2 ? 20 : 22;
  return (
    <>
      {files.map((f, i) => {
        const fx = box.x + (tier === 2 ? 16 : 18) + (i % cols) * cw;
        const fy = box.y + (node.isCycle ? 52 : 38) + Math.floor(i / cols) * rowH;
        const isSelected = selectedFileId === f.file_id;
        const shortName = f.path.split("/").pop() ?? f.path;
        return (
          <g key={f.file_id}>
            <circle
              cx={tier === 2 ? fx + 4 : fx}
              cy={fy}
              r={isSelected ? 6.5 : 4.5}
              fill={isSelected ? "#3DDC97" : "rgba(233,241,238,.46)"}
              style={{ cursor: "pointer" }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectFile(f.file_id);
              }}
            >
              <title>{f.path}</title>
            </circle>
            {tier === 2 && (
              <text
                x={fx + 12} y={fy + 3}
                fill={isSelected ? "#E9F1EE" : "rgba(233,241,238,.44)"}
                fontFamily="var(--mono)" fontSize={7.5}
                style={{ pointerEvents: "none" }}
              >
                {shortName.length > 13 ? `${shortName.slice(0, 12)}…` : shortName}
              </text>
            )}
          </g>
        );
      })}
    </>
  );
}
