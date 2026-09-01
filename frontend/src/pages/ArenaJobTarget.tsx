import { ArrowRight, ClipboardPaste, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArenaJobTargetSummaryT,
  arenaCreateJobTarget,
  arenaListJobTargets,
} from "../lib/api";

/**
 * Interview Arena entry point: paste a job title and a job description.
 *
 * The JD is the source of truth for this module, deliberately NOT the user's
 * learning roadmap — someone may interview for a role they already hold while
 * learning something else entirely, so coupling the two would build a graph
 * that tests the wrong thing.
 */
export default function ArenaJobTarget() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<ArenaJobTargetSummaryT[]>([]);

  useEffect(() => {
    arenaListJobTargets().then(setRecent).catch(() => setRecent([]));
  }, []);

  const words = jd.trim() ? jd.trim().split(/\s+/).length : 0;
  // Matches the server's floor. Below roughly this length there is no document
  // to extract from, and the honest response is to refuse rather than return a
  // graph invented from a phrase.
  const tooShort = jd.trim().length < 40;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const graph = await arenaCreateJobTarget(title.trim(), jd.trim());
      navigate(`/arena/${graph.id}/graph`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that job description");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="font-display text-2xl text-snow">Interview Arena</h1>
        <p className="mt-1 text-sm leading-relaxed text-fog">
          Paste a job description. It becomes a skill graph you review and confirm, and the
          interview is built against that graph — not against your roadmap.
        </p>
      </header>

      <div className="space-y-4 rounded-xl border border-line bg-panel p-5">
        <label className="block">
          <span className="font-mono text-[10px] uppercase tracking-wider text-fog">
            job title
          </span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Senior Forward Deployed Engineer"
            className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm text-snow outline-none focus:border-accent/50"
          />
          <span className="mt-1 block text-[11px] text-fog/70">
            Used as a weighting signal — a skill named in the title is weighted up.
          </span>
        </label>

        <label className="block">
          <div className="flex items-baseline justify-between">
            <span className="font-mono text-[10px] uppercase tracking-wider text-fog">
              job description
            </span>
            <span className="font-mono text-[10px] text-fog tabular-nums">
              {words} words
            </span>
          </div>
          <textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            rows={16}
            placeholder="Paste the full posting, including the Requirements and Preferred sections — the section a skill appears in is the strongest importance signal available."
            className="mt-1 w-full resize-y rounded-lg border border-line bg-ink px-3 py-2 font-mono text-[12px] leading-relaxed text-snow outline-none focus:border-accent/50"
          />
        </label>

        {error && (
          <div className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-[12px] text-danger">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between gap-4">
          <p className="text-[11px] leading-relaxed text-fog/70">
            Two model calls: one to read the posting, one to name the groups. Everything
            else — weights, depth, merging, grouping — is computed locally.
          </p>
          <button
            disabled={busy || tooShort}
            onClick={submit}
            className="flex shrink-0 items-center gap-2 rounded-lg border border-accent/50 bg-accent/10 px-4 py-2 text-sm text-accent hover:bg-accent/20 disabled:opacity-40"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <ClipboardPaste size={14} />}
            {busy ? "Reading the posting…" : "Build skill graph"}
          </button>
        </div>
      </div>

      {recent.length > 0 && (
        <section>
          <h2 className="font-mono text-[10px] uppercase tracking-wider text-fog">
            previous job targets
          </h2>
          <ul className="mt-2 space-y-1">
            {recent.map((row) => (
              <li key={row.id}>
                <button
                  onClick={() => navigate(`/arena/${row.id}/graph`)}
                  className="flex w-full items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2 text-left hover:bg-glass"
                >
                  <span className="min-w-0 flex-1 truncate text-sm text-snow">
                    {row.title || "Untitled role"}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-fog">
                    {row.node_count} skills
                  </span>
                  <span
                    className={`shrink-0 font-mono text-[10px] ${
                      row.graph_confirmed_at ? "text-accent" : "text-warning"
                    }`}
                  >
                    {row.graph_confirmed_at ? "confirmed" : "unconfirmed"}
                  </span>
                  <ArrowRight size={13} className="shrink-0 text-fog" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
