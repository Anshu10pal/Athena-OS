import { Check, GitMerge, X } from "lucide-react";
import { MergeSuggestionT } from "../../lib/arenaGraphEdits";

/**
 * The review band: pairs the canonicalisation cascade REFUSED to decide.
 *
 * Two design rules here are load-bearing, not stylistic.
 *
 * 1. NOTHING IS PRE-SELECTED. Every pair renders as "kept separate" and
 *    merging takes an explicit tap. An unmerged duplicate is a redundant node
 *    the user can see and delete; a false merge silently destroys a
 *    distinction the interview needed to test, and nothing downstream can
 *    notice. Errors of omission are recoverable on the next screen; errors of
 *    commission are not.
 *
 * 2. IT IS NOT A GATE. The user can start an interview with every pair still
 *    undecided — an undecided pair simply stays unmerged, which is the safe
 *    default. Forcing a decision on each would make this a chore rather than a
 *    check, and a chore is what stops the confirmation screen being read.
 *
 * Rejections are sent to the server, not discarded. They are hand-labelled
 * negative data on exactly the band where the instrument is weakest, and they
 * are what a future retune of the band floor should be measured against.
 */
export default function MergeSuggestions({
  suggestions,
  busy,
  onDecide,
}: {
  suggestions: MergeSuggestionT[];
  busy: boolean;
  onDecide: (id: number, decision: "accepted" | "rejected") => void;
}) {
  const pending = suggestions.filter((s) => s.status === "pending");
  const decided = suggestions.filter((s) => s.status !== "pending");

  if (suggestions.length === 0) return null;

  return (
    <section className="rounded-xl border border-line bg-panel2 p-4">
      <header className="flex items-baseline gap-2">
        <GitMerge size={14} className="text-info shrink-0 translate-y-0.5" />
        <h2 className="font-display text-sm text-snow">Possible duplicates</h2>
        <span className="font-mono text-[10px] text-fog">
          {pending.length} undecided
        </span>
      </header>
      <p className="mt-1 text-[11px] leading-relaxed text-fog">
        These pairs were close enough to be worth asking about and not close enough to
        merge automatically. They are <span className="text-snow">kept separate</span> unless
        you say otherwise — you can leave them and start the interview.
      </p>

      <ul className="mt-3 space-y-2">
        {pending.map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-line bg-panel px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-snow">
                {s.left_name} <span className="text-fog">·</span> {s.right_name}
              </div>
              {/* Both scores shown. The pair of numbers is the diagnostic;
                  either alone is not. `similarity` is the value that decided
                  the band; `context` is the withdrawn shadow metric, kept
                  visible because it is the only place its real-JD behaviour
                  can be observed. */}
              <div className="mt-0.5 font-mono text-[10px] text-fog/70">
                similarity {s.bare_cosine.toFixed(3)} · context {s.enriched_cosine.toFixed(3)}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                disabled={busy}
                onClick={() => onDecide(s.id, "rejected")}
                className="flex items-center gap-1 rounded border border-line px-2 py-1 font-mono text-[10px] text-fog hover:border-danger/50 hover:text-danger disabled:opacity-40"
              >
                <X size={11} /> keep separate
              </button>
              <button
                disabled={busy}
                onClick={() => onDecide(s.id, "accepted")}
                className="flex items-center gap-1 rounded border border-accent/40 bg-accent/10 px-2 py-1 font-mono text-[10px] text-accent hover:bg-accent/20 disabled:opacity-40"
              >
                <Check size={11} /> merge
              </button>
            </div>
          </li>
        ))}
      </ul>

      {decided.length > 0 && (
        <div className="mt-3 font-mono text-[10px] text-fog/70">
          {decided.filter((s) => s.status === "accepted").length} merged ·{" "}
          {decided.filter((s) => s.status === "rejected").length} kept separate
        </div>
      )}
    </section>
  );
}
