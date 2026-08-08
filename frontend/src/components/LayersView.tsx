import { useMemo, useState } from "react";
import { GraphNodeT } from "../lib/api";

// Phase G4: matches the reading list's rank-20 divider convention -- same
// number, same idea (a readable ceiling, not a hard limit on the data).
// Checked against repo 1 before picking this: layer 1 alone holds ~30
// files (main.py's fan-out is 27), so this cap engages on the very first
// column a user sees, every time. The "+N more" affordance is styled as
// an invitation (accent border/text), not a muted/greyed-out dead end,
// because it's the common case here, not an edge case.
const LAYER_COLUMN_CAP = 20;

interface Column {
  key: string;
  label: string;
  nodes: GraphNodeT[];
}

function buildColumns(nodes: GraphNodeT[]): Column[] {
  const byLayer = new Map<number, GraphNodeT[]>();
  const unreachable: GraphNodeT[] = [];
  for (const n of nodes) {
    if (n.layer === null) {
      unreachable.push(n);
    } else {
      if (!byLayer.has(n.layer)) byLayer.set(n.layer, []);
      byLayer.get(n.layer)!.push(n);
    }
  }
  const columns: Column[] = Array.from(byLayer.keys())
    .sort((a, b) => a - b)
    .map((l) => ({ key: String(l), label: `Layer ${l}`, nodes: [...byLayer.get(l)!].sort((a, b) => a.rank - b.rank) }));
  if (unreachable.length > 0) {
    // Always last, and clearly separated (border, not just position) --
    // these files are reachable by nothing from any real entry point,
    // which is a structurally different fact than "far from the entry
    // point," not merely the highest-numbered layer.
    columns.push({ key: "unreachable", label: "Unreachable", nodes: [...unreachable].sort((a, b) => a.rank - b.rank) });
  }
  return columns;
}

function LayerColumn({
  column, selectedFileId, onSelect, onOpenMermaid,
}: {
  column: Column;
  selectedFileId: number | null;
  onSelect: (id: number) => void;
  onOpenMermaid: (id: number, trigger: HTMLButtonElement) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? column.nodes : column.nodes.slice(0, LAYER_COLUMN_CAP);
  const remaining = column.nodes.length - visible.length;
  const isUnreachable = column.key === "unreachable";

  return (
    <div
      className={
        "card p-3 w-64 shrink-0 flex flex-col gap-2 " + (isUnreachable ? "border-l-2 border-l-warning/50" : "")
      }
    >
      <div className="flex items-center justify-between">
        <h4 className="font-mono text-[10px] uppercase tracking-widest text-accent">{column.label}</h4>
        <span className="font-mono text-[10px] text-fog">{column.nodes.length}</span>
      </div>
      <div className="flex flex-col gap-1.5 overflow-y-auto max-h-[65vh]">
        {visible.map((n) => (
          <div
            key={n.id}
            id={`layer-node-${n.id}`}
            onClick={() => onSelect(n.id)}
            className={
              "group rounded border px-2 py-1.5 cursor-pointer transition-colors " +
              (selectedFileId === n.id ? "border-accent bg-accent/10" : "border-line hover:border-fog")
            }
          >
            <div className="flex items-center justify-between gap-1">
              <span className="font-mono text-[10px] text-fog">#{n.rank}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenMermaid(n.id, e.currentTarget);
                }}
                aria-label={`Show ${n.path}'s neighborhood as a Mermaid diagram`}
                className="font-mono text-[9px] text-fog hover:text-accent opacity-0 group-hover:opacity-100 transition-opacity"
              >
                LR
              </button>
            </div>
            <p className="font-mono text-[11px] text-snow break-all leading-snug">{n.path}</p>
          </div>
        ))}
      </div>
      {remaining > 0 && (
        <button
          onClick={() => setExpanded(true)}
          className="font-mono text-[10px] text-accent hover:text-snow border border-accent/40 rounded px-2 py-1.5 text-center"
        >
          +{remaining} more in this layer →
        </button>
      )}
      {expanded && column.nodes.length > LAYER_COLUMN_CAP && (
        <button
          onClick={() => setExpanded(false)}
          className="font-mono text-[10px] text-fog hover:text-snow border border-line rounded px-2 py-1.5 text-center"
        >
          show fewer
        </button>
      )}
    </div>
  );
}

export function LayersView({
  nodes, selectedFileId, onSelect, onOpenMermaid,
}: {
  nodes: GraphNodeT[];
  selectedFileId: number | null;
  onSelect: (id: number) => void;
  onOpenMermaid: (id: number, trigger: HTMLButtonElement) => void;
}) {
  const columns = useMemo(() => buildColumns(nodes), [nodes]);

  if (columns.length === 0) {
    return <p className="text-fog text-sm font-mono p-5">No files match the current filters.</p>;
  }

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {columns.map((col) => (
        <LayerColumn key={col.key} column={col} selectedFileId={selectedFileId} onSelect={onSelect} onOpenMermaid={onOpenMermaid} />
      ))}
    </div>
  );
}
