import { useEffect, useRef, useState } from "react";
import { api, NeighborsResponseT, ScorerT } from "../lib/api";
import { buildMermaidNeighborhood, truncationNote } from "../lib/mermaid";
import { SlideOver } from "./SlideOver";

// Reuses this app's own existing design tokens (tailwind.config.js), not
// new colors -- Mermaid's theming API takes literal CSS color values, not
// Tailwind classes, so there's no way to hand it a class name instead.
const MERMAID_THEME_VARIABLES = {
  primaryColor: "#161D1A", // panel2
  primaryTextColor: "#E9F1EE", // snow
  primaryBorderColor: "#3DDC97", // accent
  lineColor: "#3DDC97", // accent
  background: "#070B0A", // ink
};

export function MermaidPanel({
  repoId, fileId, scorer, onClose, triggerRef,
}: {
  repoId: string;
  fileId: number | null;
  scorer: ScorerT;
  onClose: () => void;
  triggerRef: React.RefObject<HTMLButtonElement>;
}) {
  const [data, setData] = useState<NeighborsResponseT | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const open = fileId !== null;

  useEffect(() => {
    if (fileId === null) return;
    setData(null);
    setError("");
    api<NeighborsResponseT>(`/api/repos/${repoId}/files/${fileId}/neighbors?scorer=${scorer}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [repoId, fileId, scorer]);

  const built = data ? buildMermaidNeighborhood(data) : null;

  // Mermaid is a heavy rendering library (a substantial chunk of JS) needed
  // only by whoever actually opens this panel -- a dynamic import() keeps
  // it out of the app's main bundle entirely rather than paying for it on
  // every page load. See bundle-size note in the G4 report: confirmed via
  // a real build, not assumed.
  useEffect(() => {
    if (!built || !previewRef.current) return;
    let cancelled = false;
    (async () => {
      const mermaidModule = await import("mermaid");
      const mermaid = mermaidModule.default;
      mermaid.initialize({ startOnLoad: false, theme: "dark", themeVariables: MERMAID_THEME_VARIABLES });
      try {
        const { svg } = await mermaid.render(`mermaid-preview-${fileId}`, built.text);
        if (!cancelled && previewRef.current) previewRef.current.innerHTML = svg;
      } catch {
        if (!cancelled && previewRef.current) {
          previewRef.current.innerHTML = "";
          setError("Could not render a preview -- the copyable text below is still valid Mermaid syntax.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [built?.text, fileId]);

  const copy = async () => {
    if (!built) return;
    await navigator.clipboard.writeText(built.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Two independent truncation dimensions now: the backend's own file-
  // level cap (rare -- NEIGHBORS_ENDPOINT_CAP, 100), and the new 8-group-
  // per-direction cap this panel applies on top of that. Both can fire at
  // once for a pathological file; neither implies the other.
  const importerGroupNote = built
    ? truncationNote(built.importerGroupsShown.length, built.importerGroupsTotal, "importer directories")
    : null;
  const importGroupNote = built
    ? truncationNote(built.importGroupsShown.length, built.importGroupsTotal, "import directories")
    : null;

  return (
    <SlideOver open={open} onClose={onClose} triggerRef={triggerRef} title={data ? data.path : "Neighborhood"}>
      {error && <p className="text-danger text-sm mb-3">{error}</p>}
      {!data && !error && <p className="text-fog text-sm font-mono">Loading…</p>}
      {built && (
        <div className="space-y-4">
          {(importerGroupNote || importGroupNote) && (
            <div className="text-warning text-xs font-mono space-y-1">
              {importerGroupNote && <p>{importerGroupNote}</p>}
              {importGroupNote && <p>{importGroupNote}</p>}
            </div>
          )}
          <div ref={previewRef} className="bg-panel rounded border border-line p-3 overflow-x-auto" />
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="font-mono text-[10px] uppercase tracking-widest text-fog">Mermaid source</span>
              <button onClick={copy} className="font-mono text-[10px] text-accent hover:text-snow">
                {copied ? "copied!" : "copy"}
              </button>
            </div>
            <pre className="bg-panel rounded border border-line p-3 text-[11px] text-fog overflow-x-auto whitespace-pre-wrap">
              {built.text}
            </pre>
          </div>
        </div>
      )}
    </SlideOver>
  );
}
