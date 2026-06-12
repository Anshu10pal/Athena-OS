import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { DecryptText } from "../lib/fx";
import AssessmentRunner from "./AssessmentRunner";

interface Resource {
  title: string;
  url: string;
  type: string;
  note?: string;
  added_by?: string;
  source?: string;
}

interface Dossier {
  node: any;
  definition: string;
  eli5: string;
  briefing: string;
  submap_id: number | null;
  community_resources: Resource[];
  generated_links: Resource[];
  suggest_url: string;
  question_count: number;
  pass_threshold: number;
}

const TYPE_COLORS: Record<string, string> = {
  official: "text-ember bg-ember/10",
  article: "text-brass bg-brass/10",
  video: "text-sage bg-sage/10",
  course: "text-snow bg-panel2",
  opensource: "text-fog bg-panel2",
};

export default function NodeDossier({
  roadmapId,
  node,
  onClose,
  onCompleted,
  onSkip,
  onExpand,
  onRemove,
}: {
  roadmapId: number;
  node: any;
  onClose: () => void;
  onCompleted: (nodes: any[], xp: number, xpGained: number) => void;
  onSkip: () => void;
  onExpand: (submapId: number) => void;
  onRemove: () => void;
}) {
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState("");
  const [assessing, setAssessing] = useState(false);
  const [expanding, setExpanding] = useState(false);

  useEffect(() => {
    setDossier(null);
    api<Dossier>(`/api/roadmap/${roadmapId}/node/${node.id}/dossier`)
      .then(setDossier)
      .catch((e) => setError(e.message));
  }, [roadmapId, node.id]);

  const expand = async () => {
    if (!dossier) return;
    if (dossier.submap_id) {
      onExpand(dossier.submap_id);
      return;
    }
    setExpanding(true);
    try {
      const r = await api<{ id: number }>(`/api/roadmap/${roadmapId}/node/${node.id}/expand`, { method: "POST" });
      onExpand(r.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setExpanding(false);
    }
  };

  const resources = [...(dossier?.community_resources ?? []), ...(dossier?.generated_links ?? [])];

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 flex justify-end"
        style={{ zIndex: 40, background: "rgba(11,14,20,0.6)" }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="w-full max-w-md h-full bg-panel border-l border-brass/30 flex flex-col"
          initial={{ x: 60 }}
          animate={{ x: 0 }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-5 py-4 border-b border-line">
            <div className="flex items-start justify-between">
              <p className="font-mono text-[10px] tracking-[0.25em] text-brass">
                NODE DOSSIER · {node.id.toUpperCase()} · {node.status.replace("_", " ").toUpperCase()}
              </p>
              <button onClick={onClose} className="text-fog hover:text-snow">
                <X size={16} />
              </button>
            </div>
            <h3 className="font-display text-lg text-snow mt-1.5">
              <DecryptText text={node.title} />
            </h3>
            <div className="flex gap-1.5 mt-2 flex-wrap">
              <span className="font-mono text-[9px] text-fog border border-line rounded px-1.5 py-0.5">{node.skills?.length ?? 0} skills</span>
              {dossier && (
                <span className="font-mono text-[9px] text-brass border border-brass/40 rounded px-1.5 py-0.5">
                  {dossier.question_count} Q assessment · pass ≥ {dossier.pass_threshold}%
                </span>
              )}
            </div>
          </div>

          {assessing && dossier ? (
            <AssessmentRunner
              roadmapId={roadmapId}
              nodeId={node.id}
              onDone={(nodes, xp, gained) => {
                setAssessing(false);
                if (nodes) onCompleted(nodes, xp, gained);
              }}
              onBack={() => setAssessing(false)}
            />
          ) : (
            <>
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
                {error && <p className="text-ember text-sm">{error}</p>}
                {!dossier && !error && <p className="text-fog text-sm font-mono animate-pulse">Athena is compiling your briefing…</p>}
                {dossier && (
                  <>
                    {dossier.definition && (
                      <section>
                        <p className="font-mono text-[10px] tracking-widest text-fog mb-2">WHAT IT IS — EXACT MEANING</p>
                        <p className="text-sm text-snow leading-relaxed">{dossier.definition}</p>
                      </section>
                    )}
                    {dossier.eli5 && (
                      <section className="border border-brass/30 bg-brass/5 rounded-lg p-3">
                        <p className="font-mono text-[10px] tracking-widest text-brass mb-1.5">ELI5 — LIKE YOU'RE FIVE</p>
                        <p className="text-sm text-snow leading-relaxed">{dossier.eli5}</p>
                      </section>
                    )}
                    <button
                      onClick={expand}
                      disabled={expanding}
                      className="w-full border border-brass/40 bg-brass/10 rounded-lg px-3 py-2.5 font-mono text-[11px] text-brass hover:bg-brass/20 transition-colors disabled:opacity-60"
                    >
                      {expanding ? "CHARTING SUB-MAP…" : dossier.submap_id ? "◈ OPEN SUB-MAP — GRANULAR GRAPH" : "◈ EXPAND INTO SUB-MAP — GO GRANULAR"}
                    </button>
                    <p className="font-mono text-[9px] text-fog -mt-3 text-center">clear every sub-node and this node auto-completes (+100 XP)</p>
                    <section>
                      <p className="font-mono text-[10px] tracking-widest text-fog mb-2">BRIEFING — GENERATED FOR YOU</p>
                      <p className="text-sm text-snow leading-relaxed whitespace-pre-wrap">{dossier.briefing}</p>
                    </section>
                    <section>
                      <p className="font-mono text-[10px] tracking-widest text-fog mb-2">STUDY MATERIAL</p>
                      <div className="space-y-2">
                        {resources.map((r, i) => (
                          <a
                            key={i}
                            href={r.url}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-2.5 bg-panel2 border border-line rounded-lg px-3 py-2.5 hover:border-brass/40 transition-colors group"
                          >
                            <span className={`font-mono text-[8px] uppercase rounded px-1.5 py-0.5 ${TYPE_COLORS[r.type] ?? "text-fog bg-panel2"}`}>{r.type}</span>
                            <span className="text-xs text-snow flex-1 truncate">{r.title}</span>
                            {r.added_by && <span className="font-mono text-[8px] text-fog">community · {r.added_by}</span>}
                            <ExternalLink size={11} className="text-fog group-hover:text-brass shrink-0" />
                          </a>
                        ))}
                        <a
                          href={dossier.suggest_url}
                          target="_blank"
                          rel="noreferrer"
                          className="block text-center border border-dashed border-line rounded-lg px-3 py-2 font-mono text-[10px] text-fog hover:text-brass hover:border-brass/40 transition-colors"
                        >
                          + suggest a resource (opens GitHub)
                        </a>
                      </div>
                    </section>
                  </>
                )}
              </div>
              <div className="px-5 py-4 border-t border-line space-y-2">
                <div className="flex justify-between items-center">
                  <span className="font-mono text-[10px] tracking-widest text-fog">ASSESSMENT GATE</span>
                  <span className="font-mono text-[10px] text-brass">+150–225 XP</span>
                </div>
                <button className="btn-brass w-full" disabled={!dossier || node.status === "completed"} onClick={() => setAssessing(true)}>
                  {node.status === "completed" ? "Completed" : `Begin assessment — ${dossier?.question_count ?? "…"} questions`}
                </button>
                {node.status !== "completed" && node.status !== "skipped" && (
                  <button onClick={onSkip} className="w-full text-fog text-xs hover:text-snow font-mono">
                    skip — I already know this (no XP)
                  </button>
                )}
                <button
                  onClick={() => {
                    if (window.confirm(`Remove "${node.title}" from your journey? Dependents re-wire automatically.`)) onRemove();
                  }}
                  className="w-full text-fog/60 text-[10px] hover:text-ember font-mono"
                >
                  ✕ remove from my journey — not relevant to me
                </button>
              </div>
            </>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
