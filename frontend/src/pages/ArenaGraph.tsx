import { AlertTriangle, ArrowLeft, Loader2, Play, Plus, RotateCcw, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import MergeSuggestions from "../components/arena/MergeSuggestions";
import SkillNodeRow from "../components/arena/SkillNodeRow";
import {
  ArenaReadinessT,
  arenaDecideMerge,
  arenaGetJobTarget,
  arenaPatchGraph,
  arenaReadiness,
} from "../lib/api";
import {
  ArenaGraphT,
  EditSet,
  TargetTier,
  applyEdits,
  emptyEditSet,
  hasEdits,
  nodeCount,
  stageAddition,
  stageDelete,
  stageUpdate,
  structureWarnings,
  unstageDelete,
} from "../lib/arenaGraphEdits";

/**
 * The skill-graph confirmation screen.
 *
 * This is the Interview Arena's ONLY validation path. Nothing downstream can
 * tell whether the extractor read the posting correctly; a human looking at
 * this screen is the check. Two consequences shape the design:
 *
 * - Edits accumulate locally and are sent as one PATCH, so a user can rename
 *   several nodes, reparent one, delete another, see the result and still
 *   abandon the lot. A user afraid to experiment here will not validate
 *   anything.
 * - Every claim the extractor makes is inspectable: the JD sentence a skill was
 *   quoted from, the surface forms that merged into it, and the arithmetic
 *   behind its weight. A graph you can only accept or reject wholesale is not
 *   being validated, it is being rubber-stamped.
 */
export default function ArenaGraph() {
  const { id } = useParams<{ id: string }>();
  const targetId = Number(id);
  const navigate = useNavigate();

  const [graph, setGraph] = useState<ArenaGraphT | null>(null);
  const [edits, setEdits] = useState<EditSet>(emptyEditSet());
  const [readiness, setReadinessState] = useState<ArenaReadinessT | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newSkill, setNewSkill] = useState("");

  const refresh = async () => {
    const [g, r] = await Promise.all([arenaGetJobTarget(targetId), arenaReadiness(targetId)]);
    setGraph(g);
    setReadinessState(r);
    setEdits(emptyEditSet());
  };

  useEffect(() => {
    setLoading(true);
    refresh()
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load that graph"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId]);

  const view = useMemo(() => (graph ? applyEdits(graph, edits) : null), [graph, edits]);
  const warnings = useMemo(
    () => (graph ? structureWarnings(graph, edits) : []),
    [graph, edits],
  );
  const total = graph ? nodeCount(graph, edits) : 0;

  const save = async (confirm: boolean) => {
    if (!graph) return;
    setBusy(true);
    setError(null);
    try {
      await arenaPatchGraph(graph.id, edits, confirm);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save those edits");
    } finally {
      setBusy(false);
    }
  };

  const decide = async (suggestionId: number, decision: "accepted" | "rejected") => {
    if (!graph) return;
    setBusy(true);
    try {
      await arenaDecideMerge(graph.id, suggestionId, decision);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record that decision");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-fog">
        <Loader2 size={14} className="animate-spin" /> Loading skill graph…
      </div>
    );
  }
  if (!graph || !view) {
    return (
      <div className="space-y-4">
        <div className="text-danger">{error ?? "That graph could not be loaded."}</div>
        <button onClick={() => navigate("/arena")} className="text-sm text-accent">
          Back to Interview Arena
        </button>
      </div>
    );
  }

  const meta = graph.extraction_metadata ?? {};
  const extraction = meta.extraction ?? {};
  const canon = meta.canonicalisation ?? {};
  const clustering = meta.clustering ?? {};

  return (
    <div className="mx-auto max-w-4xl space-y-5 pb-16">
      <header className="space-y-2">
        <button
          onClick={() => navigate("/arena")}
          className="flex items-center gap-1 font-mono text-[10px] text-fog hover:text-snow"
        >
          <ArrowLeft size={11} /> job targets
        </button>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h1 className="font-display text-2xl text-snow">
            {graph.title || "Untitled role"}
          </h1>
          <span
            className={`font-mono text-[10px] ${
              graph.graph_confirmed_at ? "text-accent" : "text-warning"
            }`}
          >
            {graph.graph_confirmed_at ? "graph confirmed" : "awaiting your confirmation"}
          </span>
        </div>
        <p className="text-sm leading-relaxed text-fog">
          Check this before starting. Nothing downstream can tell whether the posting was read
          correctly — you are the check. Click a name to rename it, expand a row to see the
          sentence it came from.
        </p>
      </header>

      {/* Extraction provenance. Shown rather than logged: the per-JD numbers are
          how the acceptance criteria are judged, and a user who cannot see
          "3 mentions rejected" has no way to distrust a graph that deserves it. */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { label: "skills", value: total },
          { label: "groups", value: view.parents.filter((p) => (p.children?.length ?? 0) > 0).length },
          {
            label: "spans rejected",
            value: extraction.rejected ?? 0,
            warn: (extraction.rejected ?? 0) > 0,
          },
          { label: "latency", value: `${(meta.latency_seconds ?? 0).toFixed(1)}s` },
        ].map((tile) => (
          <div key={tile.label} className="rounded-lg border border-line bg-panel px-3 py-2">
            <div className="font-mono text-[10px] uppercase tracking-wider text-fog">
              {tile.label}
            </div>
            <div
              className={`font-display text-lg ${tile.warn ? "text-warning" : "text-snow"}`}
            >
              {tile.value}
            </div>
          </div>
        ))}
      </div>

      {/* A short or vague posting honestly yielding few groups is a CORRECT
          result, not a problem to fix. This line says so explicitly, because a
          user who thinks the extractor underperformed will pad the graph with
          skills the posting never named. */}
      {view.parents.length < 4 && (
        <div className="rounded-lg border border-info/30 bg-info/5 px-3 py-2 text-[12px] leading-relaxed text-info">
          This posting supported {view.parents.length} group
          {view.parents.length === 1 ? "" : "s"}. That is a complete answer for a short or
          vague posting — the graph reflects what the document actually names. Add anything
          you know the role needs, but there is nothing to correct here.
        </div>
      )}

      {warnings.map((w, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[12px] ${
            w.level === "warn"
              ? "border-warning/40 bg-warning/5 text-warning"
              : "border-line bg-panel text-fog"
          }`}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          {w.message}
        </div>
      ))}

      <MergeSuggestions
        suggestions={graph.merge_suggestions}
        busy={busy}
        onDecide={decide}
      />

      <section className="space-y-3">
        {view.parents.map((parent) => (
          <div key={parent.id} className="rounded-xl border border-line bg-panel2 p-3">
            <SkillNodeRow
              node={parent}
              isParent
              pendingDelete={edits.deletes.includes(parent.id)}
              siblingCount={parent.children?.length ?? 0}
              onRename={(nid, name) => setEdits((e) => stageUpdate(e, { id: nid, canonical_name: name }))}
              onReweight={(nid, w) => setEdits((e) => stageUpdate(e, { id: nid, jd_weight: w }))}
              onRetier={(nid, t: TargetTier) => setEdits((e) => stageUpdate(e, { id: nid, target_tier: t }))}
              onDelete={(nid) => setEdits((e) => stageDelete(e, nid))}
              onUndelete={(nid) => setEdits((e) => unstageDelete(e, nid))}
            />
            {(parent.children?.length ?? 0) > 0 && (
              <div className="mt-2 space-y-1.5 pl-4">
                {parent.children!.map((child) => (
                  <SkillNodeRow
                    key={child.id}
                    node={child}
                    isParent={false}
                    pendingDelete={edits.deletes.includes(child.id)}
                    onRename={(nid, name) => setEdits((e) => stageUpdate(e, { id: nid, canonical_name: name }))}
                    onReweight={(nid, w) => setEdits((e) => stageUpdate(e, { id: nid, jd_weight: w }))}
                    onRetier={(nid, t: TargetTier) => setEdits((e) => stageUpdate(e, { id: nid, target_tier: t }))}
                    onDelete={(nid) => setEdits((e) => stageDelete(e, nid))}
                    onUndelete={(nid) => setEdits((e) => unstageDelete(e, nid))}
                    onPromote={(nid) => setEdits((e) => stageUpdate(e, { id: nid, parent_id: 0 }))}
                  />
                ))}
              </div>
            )}
          </div>
        ))}
      </section>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel p-3">
        <input
          value={newSkill}
          onChange={(e) => setNewSkill(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newSkill.trim()) {
              setEdits((prev) => stageAddition(prev, { canonical_name: newSkill.trim() }));
              setNewSkill("");
            }
          }}
          placeholder="Add a skill the posting missed"
          className="min-w-0 flex-1 rounded-lg border border-line bg-ink px-3 py-1.5 text-sm text-snow outline-none focus:border-accent/50"
        />
        <button
          disabled={!newSkill.trim()}
          onClick={() => {
            setEdits((prev) => stageAddition(prev, { canonical_name: newSkill.trim() }));
            setNewSkill("");
          }}
          className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 font-mono text-[10px] text-fog hover:text-snow disabled:opacity-40"
        >
          <Plus size={12} /> add
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-[12px] text-danger">
          {error}
        </div>
      )}

      {/* The Start gate. `can_start` is the SERVER's answer, not re-derived here
          -- two copies of a gate is one too many, and the copy that drifts is
          always the one on screen. */}
      <footer className="sticky bottom-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel2/95 p-3 backdrop-blur">
        <div className="min-w-0 flex-1 font-mono text-[10px] text-fog">
          {hasEdits(edits)
            ? `${edits.updates.length + edits.additions.length + edits.deletes.length} unsaved edit(s)`
            : readiness?.blocking_reason ?? "ready to start"}
        </div>
        {hasEdits(edits) && (
          <button
            disabled={busy}
            onClick={() => setEdits(emptyEditSet())}
            className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 font-mono text-[10px] text-fog hover:text-snow disabled:opacity-40"
          >
            <RotateCcw size={12} /> discard
          </button>
        )}
        <button
          disabled={busy || !hasEdits(edits)}
          onClick={() => save(false)}
          className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 font-mono text-[10px] text-snow hover:bg-glass disabled:opacity-40"
        >
          <Save size={12} /> save edits
        </button>
        <button
          disabled={busy || total === 0}
          onClick={() => save(true)}
          className="flex items-center gap-2 rounded-lg border border-accent/50 bg-accent/10 px-4 py-1.5 text-sm text-accent hover:bg-accent/20 disabled:opacity-40"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {graph.graph_confirmed_at ? "Re-confirm graph" : "Confirm graph"}
        </button>
      </footer>

      {/* Phase A ends at a confirmed graph. Saying so is better than a disabled
          button with no explanation, and better than a link to a screen that
          does not exist yet. */}
      {readiness?.can_start && !hasEdits(edits) && (
        <div className="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-[12px] leading-relaxed text-accent">
          Graph confirmed — this is where the interview will start from. Question generation
          and the session itself are the next phase and are not built yet.
        </div>
      )}

      <details className="rounded-lg border border-line bg-panel px-3 py-2">
        <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-wider text-fog">
          extraction detail
        </summary>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[10px] text-fog">
          <dt>extractor version</dt>
          <dd className="text-snow">{graph.extractor_version}</dd>
          <dt>model calls</dt>
          <dd className="text-snow">{meta.llm_calls ?? "—"}</dd>
          <dt>mentions accepted</dt>
          <dd className="text-snow">{extraction.accepted ?? "—"}</dd>
          <dt>spans rejected</dt>
          <dd className="text-snow">{extraction.rejected ?? "—"}</dd>
          <dt>nodes after merging</dt>
          <dd className="text-snow">{canon.nodes_after ?? "—"}</dd>
          <dt>merge methods</dt>
          <dd className="text-snow">
            {canon.merge_methods
              ? Object.entries(canon.merge_methods)
                  .filter(([, v]) => (v as number) > 0)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(" · ") || "none"
              : "—"}
          </dd>
          <dt>cluster coherence</dt>
          <dd className="text-snow">
            {clustering.coherent_fraction === null || clustering.coherent_fraction === undefined
              ? "not applicable"
              : `${Math.round(clustering.coherent_fraction * 100)}% of groups`}
          </dd>
          <dt>sections found</dt>
          <dd className="text-snow">{(meta.sections_found ?? []).join(", ") || "—"}</dd>
        </dl>
      </details>
    </div>
  );
}
