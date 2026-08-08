import { useMemo, useState } from "react";
import { DirEdgeT, DirNodeT } from "../lib/api";
import { buildWeightLookup, findSymmetricPairs, weightBetween } from "../lib/matrixLayout";

// Above this printed weight, the cell shows its number directly -- the
// strongest couplings are readable without hovering every cell. Matches
// the reference mockup's own threshold.
const PRINT_THRESHOLD = 8;

export function MatrixView({
  nodes, edges, onSelectPair,
}: {
  nodes: DirNodeT[];
  edges: DirEdgeT[];
  onSelectPair: (a: string, b: string) => void;
}) {
  const [hoverRow, setHoverRow] = useState<string | null>(null);
  const lookup = useMemo(() => buildWeightLookup(edges), [edges]);
  const maxWeight = useMemo(() => Math.max(1, ...edges.map((e) => e.weight)), [edges]);
  const symmetricPairs = useMemo(() => findSymmetricPairs(nodes, edges), [nodes, edges]);
  const cyclePairKeys = useMemo(() => {
    const s = new Set<string>();
    for (const p of symmetricPairs) {
      s.add(`${p.a}|${p.b}`);
      s.add(`${p.b}|${p.a}`);
    }
    return s;
  }, [symmetricPairs]);

  return (
    <div className="space-y-3">
      <p className="font-mono text-[10px] text-fog tracking-wide">
        ROWS DEPEND ON COLUMNS · OUTLINED CELLS ARE CYCLES · {symmetricPairs.length} FOUND
      </p>
      <div className="card overflow-auto" style={{ maxHeight: 620 }}>
        <table className="border-collapse font-mono text-[10px]">
          <thead>
            <tr>
              <th className="sticky left-0 top-0 z-20 bg-ink" />
              {nodes.map((c) => (
                <th
                  key={c.id}
                  className="sticky top-0 z-10 bg-ink px-1 py-1 font-normal text-fog whitespace-nowrap align-bottom"
                  style={{ height: 110 }}
                  title={c.path}
                >
                  <div style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }} className="text-left">
                    {c.short_label}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {nodes.map((r) => (
              <tr
                key={r.id}
                onMouseEnter={() => setHoverRow(r.id)}
                onMouseLeave={() => setHoverRow(null)}
                className={hoverRow === r.id ? "bg-glass" : undefined}
              >
                <th
                  className={
                    "sticky left-0 z-10 bg-ink px-2 py-0.5 text-right font-normal whitespace-nowrap " +
                    (hoverRow === r.id ? "text-accent" : "text-fog")
                  }
                  title={r.path}
                >
                  {r.short_label}
                </th>
                {nodes.map((c) => {
                  if (r.id === c.id) {
                    // Not a silent dead cell: the diagonal is where H1's
                    // internal_edge_count actually lives (edges dropped
                    // from every off-diagonal cell specifically because
                    // they're internal to this one directory). Shown, not
                    // clickable -- "filter the map to a pair" has no
                    // meaning for a single directory against itself.
                    return (
                      <td
                        key={c.id}
                        title={`${r.short_label}: ${r.internal_edge_count} internal edge${r.internal_edge_count === 1 ? "" : "s"}`}
                        className="w-[22px] h-[22px] text-center bg-glass border border-line/40 text-fog-2"
                      >
                        {r.internal_edge_count > 0 ? r.internal_edge_count : ""}
                      </td>
                    );
                  }
                  const w = weightBetween(lookup, r.id, c.id);
                  const isCycle = w > 0 && cyclePairKeys.has(`${r.id}|${c.id}`);
                  const alpha = w > 0 ? 0.16 + (w / maxWeight) * 0.84 : 0;
                  return (
                    <td
                      key={c.id}
                      onClick={() => w > 0 && onSelectPair(r.id, c.id)}
                      title={`${r.short_label} → ${c.short_label}: ${w.toFixed(2)}`}
                      className={
                        "w-[22px] h-[22px] text-center border " +
                        (isCycle ? "border-danger" : "border-line/40") +
                        (w > 0 ? " cursor-pointer" : "")
                      }
                      style={{
                        background: w > 0 ? `rgba(61,220,151,${alpha})` : "transparent",
                        outline: isCycle ? "1.5px solid var(--danger, #E2646E)" : undefined,
                        outlineOffset: isCycle ? "-1.5px" : undefined,
                        color: "#04120C",
                      }}
                    >
                      {w >= PRINT_THRESHOLD ? Math.round(w) : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
