import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { DecryptText } from "../lib/fx";

interface RoadmapNodeT {
  id: number;
  title: string;
  blurb: string;
  module_slug: string | null;
  resolution: "matched" | "unmatched";
  match_score: number | null;
  percent: number | null;
}

interface StageT {
  title: string;
  nodes: RoadmapNodeT[];
}

interface RoadmapResult {
  id: number;
  slug: string;
  title: string;
  target: string;
  kind: "seed" | "generated";
  summary: string;
  resolved_via: "seed" | "cached" | "generated";
  percent: number;
  topic_count: number;
  completed_count: number;
  stages: StageT[];
}

interface RoadmapTile {
  slug: string;
  title: string;
  summary: string;
  category: "role" | "tool";
  kind: "seed" | "generated";
  percent: number;
}

const VIA_LABEL: Record<RoadmapResult["resolved_via"], string> = {
  seed: "curated",
  cached: "cached",
  generated: "freshly generated",
};

function TileGrid({ tiles, onOpen }: { tiles: RoadmapTile[]; onOpen: (slug: string) => void }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {tiles.map((t) => (
        <button
          key={t.slug}
          onClick={() => onOpen(t.slug)}
          className="card text-left p-5 min-h-[148px] flex flex-col hover:border-accent/50 transition-colors"
        >
          <p className="font-display text-lg font-semibold text-snow leading-snug">{t.title}</p>
          {t.summary && <p className="text-fog text-sm mt-2 leading-relaxed line-clamp-3 flex-1">{t.summary}</p>}
          <div className="mt-4 flex items-center gap-2.5">
            <div className="flex-1 h-1.5 rounded-full bg-line overflow-hidden">
              <div className="h-full bg-accent" style={{ width: `${t.percent}%` }} />
            </div>
            <span className="font-mono text-[10px] text-accent shrink-0">{t.percent}%</span>
          </div>
        </button>
      ))}
    </div>
  );
}

export default function Roadmap() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [tiles, setTiles] = useState<RoadmapTile[] | null>(null);
  const [result, setResult] = useState<RoadmapResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [openingId, setOpeningId] = useState<number | null>(null);

  const loadTiles = () => api<RoadmapTile[]>("/api/roadmaps").then(setTiles).catch(() => {});

  useEffect(() => {
    loadTiles();
  }, []);

  const openBySlug = async (slug: string) => {
    setBusy(true);
    setError("");
    try {
      const r = await api<RoadmapResult>(`/api/roadmaps/${slug}`);
      setResult(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    if (!query.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await api<RoadmapResult>("/api/roadmaps/search", {
        method: "POST",
        body: JSON.stringify({ query: query.trim() }),
      });
      setResult(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const backToRoadmaps = () => {
    setResult(null);
    setQuery("");
    loadTiles(); // percents may have changed since progress was made
  };

  const openNode = async (node: RoadmapNodeT) => {
    if (!result || openingId) return;
    if (node.resolution === "matched" && node.module_slug) {
      navigate(`/modules/${node.module_slug}?from=${encodeURIComponent(result.title)}`);
      return;
    }
    setOpeningId(node.id);
    try {
      const r = await api<{ module_slug: string }>(`/api/roadmaps/nodes/${node.id}/ensure-module`, {
        method: "POST",
      });
      navigate(`/modules/${r.module_slug}?from=${encodeURIComponent(result.title)}`);
    } catch (e: any) {
      setError(e.message);
      setOpeningId(null);
    }
  };

  const started = (tiles ?? []).filter((t) => t.percent > 0);
  const startedSlugs = new Set(started.map((t) => t.slug));
  const roleBased = (tiles ?? []).filter((t) => t.category === "role" && !startedSlugs.has(t.slug));
  const toolBased = (tiles ?? []).filter((t) => t.category === "tool" && !startedSlugs.has(t.slug));

  return (
    <div className="w-full max-w-none space-y-6">
      <div className="card p-5">
        <h2 className="font-display text-xl font-semibold">
          <DecryptText text="Roadmap engine" />
        </h2>
        <div className="flex gap-2 mt-3">
          <input
            className="input"
            placeholder="Or type any target role or tool, e.g. AI Architect"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
          <button className="btn-accent shrink-0" onClick={search} disabled={busy}>
            {busy ? "Searching…" : "Search"}
          </button>
        </div>
        {error && <p className="text-danger text-sm mt-2">{error}</p>}
      </div>

      {!result && (
        <div className="space-y-6">
          {started.length > 0 && (
            <div>
              <p className="font-mono text-[10px] tracking-widest text-fog mb-2 uppercase">Ongoing</p>
              <TileGrid tiles={started} onOpen={openBySlug} />
            </div>
          )}
          {roleBased.length > 0 && (
            <div>
              <p className="font-mono text-[10px] tracking-widest text-fog mb-2 uppercase">Role-based</p>
              <TileGrid tiles={roleBased} onOpen={openBySlug} />
            </div>
          )}
          {toolBased.length > 0 && (
            <div>
              <p className="font-mono text-[10px] tracking-widest text-fog mb-2 uppercase">Tool-based</p>
              <TileGrid tiles={toolBased} onOpen={openBySlug} />
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="card p-5">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
            <div className="flex items-center gap-3">
              <button onClick={backToRoadmaps} className="font-mono text-[11px] text-fog hover:text-snow">
                ← back to roadmaps
              </button>
              <h3 className="font-display text-lg">{result.title}</h3>
            </div>
            <span className="font-mono text-[9px] text-fog border border-line rounded px-1.5 py-0.5">
              {VIA_LABEL[result.resolved_via]}
            </span>
          </div>
          {result.summary && <p className="text-fog text-sm mb-3">{result.summary}</p>}
          <div className="flex items-center gap-2.5 mb-5">
            <div className="flex-1 h-1.5 rounded-full bg-line overflow-hidden max-w-xs">
              <div className="h-full bg-accent" style={{ width: `${result.percent}%` }} />
            </div>
            <span className="font-mono text-[10px] text-accent">
              {result.percent}% complete &middot; {result.completed_count} of {result.topic_count} topics
            </span>
          </div>

          <div className="space-y-5">
            {result.stages.map((stage, si) => (
              <div key={si}>
                <p className="font-mono text-[10px] tracking-widest text-fog mb-2 uppercase">{stage.title}</p>
                <div className="relative pl-7">
                  <div className="absolute left-[8px] top-2 bottom-2 w-px bg-line" />
                  {stage.nodes.map((node, ni) => (
                    <motion.div
                      key={node.id}
                      initial={{ opacity: 0, x: -12 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: ni * 0.04 }}
                      className="relative pb-4"
                    >
                      <span className="absolute -left-7 top-4 w-2.5 h-2.5 rounded-full bg-accent" />
                      <button
                        onClick={() => openNode(node)}
                        disabled={openingId === node.id}
                        className="w-full text-left rounded-lg border border-accent/40 bg-panel2 px-4 py-3 hover:border-accent transition-colors disabled:opacity-60"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="font-medium text-snow">
                            {node.title}
                            {node.resolution === "unmatched" && (
                              <span className="font-mono text-[8px] text-fog ml-2 border border-line rounded px-1 py-0.5">
                                NEW MODULE
                              </span>
                            )}
                          </p>
                          {node.percent !== null && (
                            <span className="font-mono text-[9px] text-accent shrink-0">{node.percent}%</span>
                          )}
                        </div>
                        <p className="text-fog text-sm mt-1">{openingId === node.id ? "Opening…" : node.blurb}</p>
                      </button>
                    </motion.div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
