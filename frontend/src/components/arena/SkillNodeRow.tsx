import { ChevronDown, ChevronRight, Pencil, Trash2, Undo2 } from "lucide-react";
import { useState } from "react";
import {
  MAX_CHILDREN_PER_PARENT,
  SkillNodeT,
  TARGET_TIERS,
  TargetTier,
} from "../../lib/arenaGraphEdits";

const TIER_LABEL: Record<TargetTier, string> = {
  expert: "expert",
  proficient: "proficient",
  working: "working",
  awareness: "awareness",
};

/** Weight rendered as a bar rather than a number alone: the ordering between
 *  skills is what the user is checking, and a column of three-decimal floats
 *  makes that comparison harder, not easier. The number stays visible for
 *  anyone who wants it. */
function WeightBar({ weight }: { weight: number }) {
  return (
    <div className="flex items-center gap-2 shrink-0" title={`JD weight ${weight.toFixed(2)}`}>
      <div className="h-1 w-16 rounded-full bg-glass overflow-hidden">
        <div
          className="h-full rounded-full bg-accent/70"
          style={{ width: `${Math.max(4, Math.min(100, weight * 100))}%` }}
        />
      </div>
      <span className="font-mono text-[10px] text-fog tabular-nums">{weight.toFixed(2)}</span>
    </div>
  );
}

interface Props {
  node: SkillNodeT;
  isParent: boolean;
  pendingDelete: boolean;
  siblingCount?: number;
  onRename: (id: number, name: string) => void;
  onReweight: (id: number, weight: number) => void;
  onRetier: (id: number, tier: TargetTier) => void;
  onDelete: (id: number) => void;
  onUndelete: (id: number) => void;
  onPromote?: (id: number) => void;
}

export default function SkillNodeRow({
  node,
  isParent,
  pendingDelete,
  siblingCount,
  onRename,
  onReweight,
  onRetier,
  onDelete,
  onUndelete,
  onPromote,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(node.canonical_name);
  const [showProvenance, setShowProvenance] = useState(false);

  const commit = () => {
    const next = draft.trim();
    if (next && next !== node.canonical_name) onRename(node.id, next);
    else setDraft(node.canonical_name);
    setEditing(false);
  };

  // A merged node hides what it absorbed behind one canonical name. That is the
  // ONE thing about canonicalisation a human needs to be able to check, so the
  // surface forms are surfaced rather than buried.
  const merged = node.surface_forms.length > 1;

  return (
    <div
      className={`rounded-lg border px-3 py-2 transition-colors ${
        pendingDelete
          ? "border-danger/40 bg-danger/5 opacity-60"
          : "border-line bg-panel hover:bg-glass"
      }`}
    >
      <div className="flex items-center gap-3">
        {(merged || node.source_spans.length > 0) && (
          <button
            onClick={() => setShowProvenance((v) => !v)}
            className="text-fog hover:text-snow shrink-0"
            aria-label={showProvenance ? "Hide evidence" : "Show evidence"}
          >
            {showProvenance ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        )}

        {editing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") {
                setDraft(node.canonical_name);
                setEditing(false);
              }
            }}
            className="flex-1 min-w-0 bg-ink border border-accent/50 rounded px-2 py-0.5 text-sm text-snow outline-none"
          />
        ) : (
          <button
            onClick={() => setEditing(true)}
            className={`flex-1 min-w-0 text-left truncate ${
              isParent ? "font-display text-sm text-snow" : "text-sm text-snow/90"
            } ${pendingDelete ? "line-through" : ""}`}
            title="Click to rename"
          >
            {node.canonical_name}
            {node.user_edited && <span className="ml-2 text-[10px] text-info">edited</span>}
            {node.extraction_source === "user_added" && (
              <span className="ml-2 text-[10px] text-accent">added by you</span>
            )}
          </button>
        )}

        {!isParent && (
          <select
            value={node.target_tier}
            onChange={(e) => onRetier(node.id, e.target.value as TargetTier)}
            className="shrink-0 bg-ink border border-line rounded px-1.5 py-0.5 font-mono text-[10px] text-fog outline-none focus:border-accent/50"
            title="Target depth inferred from the JD's experience qualifier"
          >
            {TARGET_TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {TIER_LABEL[tier]}
              </option>
            ))}
          </select>
        )}

        <WeightBar weight={node.jd_weight} />

        {!isParent && onPromote && !pendingDelete && (
          <button
            onClick={() => onPromote(node.id)}
            className="shrink-0 font-mono text-[10px] text-fog hover:text-accent"
            title="Promote to its own group"
          >
            promote
          </button>
        )}

        {pendingDelete ? (
          <button
            onClick={() => onUndelete(node.id)}
            className="shrink-0 text-fog hover:text-accent"
            aria-label="Undo delete"
            title="Undo delete"
          >
            <Undo2 size={14} />
          </button>
        ) : (
          <button
            onClick={() => onDelete(node.id)}
            className="shrink-0 text-fog hover:text-danger"
            aria-label={`Delete ${node.canonical_name}`}
            title={isParent ? "Delete this group (its skills move to the top level)" : "Delete"}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      {/* The weight explanation, always available. The requirement it serves is
          "explain a weight to someone who asks" -- so it is read from the
          persisted breakdown, which is provably the arithmetic that produced the
          stored number, rather than recomputed here. */}
      {node.weight_explanation && (
        <div className="mt-1 pl-1 font-mono text-[10px] text-fog/70 truncate"
             title={node.weight_explanation}>
          {node.weight_explanation}
        </div>
      )}

      {isParent && typeof siblingCount === "number" && siblingCount > MAX_CHILDREN_PER_PARENT && (
        <div className="mt-1 font-mono text-[10px] text-warning">
          {siblingCount} skills — over the limit of {MAX_CHILDREN_PER_PARENT}
        </div>
      )}

      {showProvenance && (
        <div className="mt-2 space-y-2 border-t border-line pt-2">
          {merged && (
            <div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-fog">
                merged surface forms
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {node.surface_forms.map((form) => (
                  <span
                    key={form}
                    className="rounded bg-glass px-1.5 py-0.5 font-mono text-[10px] text-snow/80"
                  >
                    {form}
                  </span>
                ))}
              </div>
              {node.merge_evidence.length > 0 && (
                <div className="mt-1 font-mono text-[10px] text-fog/70">
                  {node.merge_evidence
                    .map((e) => `${e.surface} via ${e.method}${e.score < 1 ? ` ${e.score.toFixed(3)}` : ""}`)
                    .join(" · ")}
                </div>
              )}
            </div>
          )}
          {node.source_spans.length > 0 && (
            <div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-fog">
                quoted from the job description
              </div>
              <ul className="mt-1 space-y-1">
                {node.source_spans.slice(0, 4).map((span, i) => (
                  <li key={i} className="text-[11px] leading-snug text-snow/70">
                    <span className="font-mono text-[10px] text-info">[{span.section}]</span>{" "}
                    {span.span}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
