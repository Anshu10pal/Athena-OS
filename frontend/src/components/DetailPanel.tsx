import { useEffect, useState } from "react";
import { api, DirEdgeT, DirNodeT, NeighborsResponseT, ScorerT } from "../lib/api";
import { findSymmetricPairs } from "../lib/matrixLayout";
import { buildMermaidNeighborhood } from "../lib/mermaid";
import { groupNeighborsByDirectory } from "../lib/neighborGrouping";

// Phase H5: ONE persistent panel, not a slide-over -- rendered alongside
// whichever view is active (see RepoDetail's flex wrapper), driven by the
// same shared selectedFileId/selectedDirId state every view already
// reads or writes. "The primary detail panel should not cover the graph
// it describes": a slide-over here would sit on top of the architecture
// map exactly when you're most likely to want both visible together.
// The Mermaid SlideOver stays a modal on purpose -- that's the heavier,
// rendered-preview experience; this panel shows the same export as plain
// copyable text, the lighter-weight companion view.
export function DetailPanel({
  repoId, scorer, selectedFileId, selectedDirId, dirNodes, dirEdges, onSelectFile, onOpenMermaidModal,
}: {
  repoId: string;
  scorer: ScorerT;
  selectedFileId: number | null;
  selectedDirId: string | null;
  dirNodes: DirNodeT[];
  dirEdges: DirEdgeT[];
  onSelectFile: (fileId: number) => void;
  onOpenMermaidModal: (fileId: number, trigger: HTMLButtonElement) => void;
}) {
  const [fileData, setFileData] = useState<NeighborsResponseT | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (selectedFileId === null) {
      setFileData(null);
      return;
    }
    setFileData(null);
    setError("");
    api<NeighborsResponseT>(`/api/repos/${repoId}/files/${selectedFileId}/neighbors?scorer=${scorer}`)
      .then(setFileData)
      .catch((e) => setError(e.message));
  }, [repoId, selectedFileId, scorer]);

  if (selectedFileId !== null) {
    if (error) return <div className="card p-4 text-danger text-xs">{error}</div>;
    if (!fileData) return <div className="card p-4 text-fog text-xs font-mono">Loading…</div>;

    const importerGroups = groupNeighborsByDirectory(fileData.importers);
    const importGroups = groupNeighborsByDirectory(fileData.imports);
    const built = buildMermaidNeighborhood(fileData);

    return (
      <div className="card p-4 space-y-3">
        <h3 className="font-mono text-[10px] uppercase tracking-widest text-accent">File</h3>
        <p className="font-mono text-xs text-snow break-all">{fileData.path}</p>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-xs">
          <dt className="text-fog">Imported by</dt>
          <dd className="text-snow">{fileData.importers_total_before_cap}</dd>
          <dt className="text-fog">Imports</dt>
          <dd className="text-snow">{fileData.imports_total_before_cap}</dd>
        </dl>
        <div>
          <h4 className="font-mono text-[10px] uppercase tracking-widest text-fog mb-1.5">Imported by</h4>
          {importerGroups.length === 0 && <p className="text-fog text-xs font-mono">None</p>}
          <ul className="space-y-1">
            {importerGroups.slice(0, 5).map((g) => (
              <li key={g.dir}>
                <button
                  onClick={() => onSelectFile(g.files[0].file_id)}
                  className="font-mono text-[11px] text-fog hover:text-accent"
                >
                  {g.dir}/ <span className="text-fog/70">×{g.count}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="font-mono text-[10px] uppercase tracking-widest text-fog mb-1.5">Imports</h4>
          {importGroups.length === 0 && <p className="text-fog text-xs font-mono">None internal</p>}
          <ul className="space-y-1">
            {importGroups.slice(0, 5).map((g) => (
              <li key={g.dir}>
                <button
                  onClick={() => onSelectFile(g.files[0].file_id)}
                  className="font-mono text-[11px] text-fog hover:text-accent"
                >
                  {g.dir}/ <span className="text-fog/70">×{g.count}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="font-mono text-[10px] uppercase tracking-widest text-fog">Mermaid — aggregated</span>
            <button
              onClick={() => navigator.clipboard.writeText(built.text)}
              className="font-mono text-[10px] text-accent hover:text-snow"
            >
              copy
            </button>
          </div>
          <pre className="bg-panel rounded border border-line p-2 text-[10px] text-fog overflow-x-auto whitespace-pre-wrap">
            {built.text}
          </pre>
        </div>
        <button
          onClick={(e) => onOpenMermaidModal(selectedFileId, e.currentTarget)}
          className="w-full font-mono text-[10px] uppercase tracking-widest text-fog hover:text-accent border border-line rounded px-2 py-1.5"
        >
          Open rendered diagram
        </button>
      </div>
    );
  }

  if (selectedDirId !== null) {
    const dir = dirNodes.find((n) => n.id === selectedDirId);
    if (!dir) return null;
    const dependsOn = dirEdges.filter((e) => e.source === selectedDirId);
    const usedBy = dirEdges.filter((e) => e.target === selectedDirId);
    const cyclePartner = findSymmetricPairs(dirNodes, dirEdges).find((p) => p.a === selectedDirId || p.b === selectedDirId);

    return (
      <div className="card p-4 space-y-3">
        <h3 className="font-mono text-[10px] uppercase tracking-widest text-accent">Directory</h3>
        <p className="font-mono text-xs text-snow break-all">{dir.path}</p>
        {cyclePartner && (
          <div className="border border-danger/40 bg-danger/10 rounded p-2.5 text-xs text-fog-2 leading-relaxed">
            <b className="text-danger">Dependency cycle.</b> This directory and{" "}
            {(cyclePartner.a === selectedDirId ? cyclePartner.b : cyclePartner.a).split("/").pop()} import each
            other. Check the Matrix tab for the exact edge counts in each direction.
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-xs">
          <dt className="text-fog">Files</dt>
          <dd className="text-snow">{dir.file_count}</dd>
          <dt className="text-fog">Kind</dt>
          <dd className="text-snow">{dir.kind}</dd>
          <dt className="text-fog">Depends on</dt>
          <dd className="text-snow">{dependsOn.length}</dd>
          <dt className="text-fog">Used by</dt>
          <dd className="text-snow">{usedBy.length}</dd>
        </dl>
        <div>
          <h4 className="font-mono text-[10px] uppercase tracking-widest text-fog mb-1.5">Depends on</h4>
          {dependsOn.length === 0 && <p className="text-fog text-xs font-mono">Nothing internal — terminal dependency</p>}
          <ul className="space-y-1">
            {dependsOn.map((e) => {
              const target = dirNodes.find((n) => n.id === e.target);
              return (
                <li key={e.target} className="font-mono text-[11px] text-fog flex justify-between">
                  <span>{target?.short_label ?? e.target}</span>
                  <span className="text-fog/70">· {e.weight.toFixed(1)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="card p-4 text-xs text-fog leading-relaxed space-y-2">
      <p>Select a directory on the Architecture map, a cell in the Matrix, or a file anywhere to see its details here.</p>
      <p>This panel stays put across tabs — the same selection follows you from Architecture to Matrix to Focus.</p>
    </div>
  );
}
