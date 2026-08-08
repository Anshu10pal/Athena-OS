import { useEffect, useState } from "react";
import { api, NeighborsResponseT, NeighborT, ScorerT } from "../lib/api";
import { groupNeighborsByDirectory, NeighborGroup, shortDirLabel } from "../lib/neighborGrouping";

// Phase H4: importers/imports grouped by directory and collapsed to a
// count -- the same aggregation principle as the architecture map and
// the Mermaid export, applied here too. This is what makes a 21-importer
// file legible: api/ ×14, not fourteen separate cards.

const MAX_DEPTH2_FETCHES = 10; // bounds the request fan-out when depth 2 is toggled on

function GroupCard({
  group, side, expandedKey, isExpanded, onToggle, onSelectFile,
}: {
  group: NeighborGroup;
  side: "in" | "out";
  expandedKey: string;
  isExpanded: boolean;
  onToggle: (key: string) => void;
  onSelectFile: (fileId: number) => void;
}) {
  const accent = side === "in" ? "border-l-info" : "border-l-accent";
  return (
    <div className={`card border-l-2 ${accent} p-3`}>
      <button
        onClick={() => onToggle(expandedKey)}
        className="w-full flex items-center justify-between text-left"
      >
        <span className="font-mono text-xs text-snow">{shortDirLabel(group.dir)}/</span>
        <span className="font-mono text-[10px] text-fog">×{group.count} {isExpanded ? "−" : "+"}</span>
      </button>
      {isExpanded && (
        <ul className="mt-2 space-y-1 border-t border-line pt-2">
          {group.files.map((f) => (
            <li key={f.file_id}>
              <button
                onClick={() => onSelectFile(f.file_id)}
                className="font-mono text-[11px] text-fog hover:text-accent text-left break-all"
              >
                {f.path}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function GroupColumn({
  title, groups, side, expanded, onToggle, onSelectFile,
}: {
  title: string;
  groups: NeighborGroup[];
  side: "in" | "out";
  expanded: Set<string>;
  onToggle: (key: string) => void;
  onSelectFile: (fileId: number) => void;
}) {
  return (
    <div className="flex-1 min-w-0 space-y-2">
      <h4 className={"font-mono text-[10px] uppercase tracking-widest " + (side === "in" ? "text-info" : "text-accent")}>
        {title}
      </h4>
      {groups.length === 0 && <p className="text-fog text-xs font-mono">None</p>}
      {groups.map((g) => {
        const key = `${side}:${g.dir}`;
        return (
          <GroupCard
            key={key}
            group={g}
            side={side}
            expandedKey={key}
            isExpanded={expanded.has(key)}
            onToggle={onToggle}
            onSelectFile={onSelectFile}
          />
        );
      })}
    </div>
  );
}

export function FocusView({
  repoId, fileId, scorer, onSelectFile,
}: {
  repoId: string;
  fileId: number | null;
  scorer: ScorerT;
  onSelectFile: (fileId: number) => void;
}) {
  const [data, setData] = useState<NeighborsResponseT | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [depth2On, setDepth2On] = useState(false);
  const [depth2Importers, setDepth2Importers] = useState<NeighborT[]>([]);
  const [depth2Imports, setDepth2Imports] = useState<NeighborT[]>([]);
  const [depth2Loading, setDepth2Loading] = useState(false);
  const [depth2Truncated, setDepth2Truncated] = useState(false);

  useEffect(() => {
    setExpanded(new Set());
    setDepth2On(false);
    setDepth2Importers([]);
    setDepth2Imports([]);
    if (fileId === null) {
      setData(null);
      return;
    }
    setData(null);
    setError("");
    api<NeighborsResponseT>(`/api/repos/${repoId}/files/${fileId}/neighbors?scorer=${scorer}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [repoId, fileId, scorer]);

  function toggleGroup(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  // Depth 2, opt-in: one more hop out from a BOUNDED set of depth-1 files
  // (not all of them -- a 21-importer file would mean 21 more requests).
  // Excludes anything already at depth 0 (the center) or depth 1 to avoid
  // rendering an edge back to something already on screen as if it were
  // new information.
  async function loadDepth2() {
    if (!data || fileId === null) return;
    setDepth2Loading(true);
    const depth1Ids = new Set([fileId, ...data.importers.map((n) => n.file_id), ...data.imports.map((n) => n.file_id)]);
    const candidates = [...data.importers, ...data.imports].slice(0, MAX_DEPTH2_FETCHES);
    setDepth2Truncated(data.importers.length + data.imports.length > MAX_DEPTH2_FETCHES);
    const results = await Promise.all(
      candidates.map((n) =>
        api<NeighborsResponseT>(`/api/repos/${repoId}/files/${n.file_id}/neighbors?scorer=${scorer}`).catch(() => null),
      ),
    );
    const importers: NeighborT[] = [];
    const imports: NeighborT[] = [];
    for (const r of results) {
      if (!r) continue;
      for (const n of r.importers) if (!depth1Ids.has(n.file_id)) importers.push(n);
      for (const n of r.imports) if (!depth1Ids.has(n.file_id)) imports.push(n);
    }
    setDepth2Importers(importers);
    setDepth2Imports(imports);
    setDepth2Loading(false);
  }

  function toggleDepth2() {
    const next = !depth2On;
    setDepth2On(next);
    if (next && depth2Importers.length === 0 && depth2Imports.length === 0) {
      loadDepth2();
    }
  }

  if (fileId === null) {
    return (
      <div className="card p-8 text-center text-fog text-sm font-mono">
        Search a file, or select one from the Architecture map or Layers view.
      </div>
    );
  }
  if (error) return <p className="text-danger text-sm">{error}</p>;
  if (!data) return <p className="text-fog text-sm font-mono">Loading…</p>;

  const importerGroups = groupNeighborsByDirectory(data.importers);
  const importGroups = groupNeighborsByDirectory(data.imports);
  const depth2ImporterGroups = groupNeighborsByDirectory(depth2Importers);
  const depth2ImportGroups = groupNeighborsByDirectory(depth2Imports);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] text-fog tracking-wide">IMPORTED BY ← CENTER → IMPORTS</p>
        <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-fog cursor-pointer">
          <input type="checkbox" checked={depth2On} onChange={toggleDepth2} className="accent-accent" />
          Show depth 2
        </label>
      </div>

      <div className="flex items-start gap-4">
        {depth2On && (
          <GroupColumn
            title="Depth 2 · imported by"
            groups={depth2ImporterGroups}
            side="in"
            expanded={expanded}
            onToggle={toggleGroup}
            onSelectFile={onSelectFile}
          />
        )}
        <GroupColumn
          title="Imported by"
          groups={importerGroups}
          side="in"
          expanded={expanded}
          onToggle={toggleGroup}
          onSelectFile={onSelectFile}
        />
        <div className="w-56 shrink-0">
          <div className="card border-2 border-accent bg-accent/10 p-4 text-center">
            <p className="font-mono text-sm text-snow break-all">{data.path.split("/").pop()}</p>
            <p className="font-mono text-[10px] text-fog mt-1 break-all">{data.path}</p>
          </div>
        </div>
        <GroupColumn
          title="Imports"
          groups={importGroups}
          side="out"
          expanded={expanded}
          onToggle={toggleGroup}
          onSelectFile={onSelectFile}
        />
        {depth2On && (
          <GroupColumn
            title="Depth 2 · imports"
            groups={depth2ImportGroups}
            side="out"
            expanded={expanded}
            onToggle={toggleGroup}
            onSelectFile={onSelectFile}
          />
        )}
      </div>

      {depth2On && depth2Loading && <p className="text-fog text-xs font-mono">Loading depth 2…</p>}
      {depth2On && depth2Truncated && (
        <p className="text-warning text-xs font-mono">
          Depth 2 fetched from the first {MAX_DEPTH2_FETCHES} of {data.importers.length + data.imports.length} depth-1 files only.
        </p>
      )}
    </div>
  );
}
