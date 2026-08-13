import { useState } from "react";
import { createPortal } from "react-dom";
import { api, RepoDeletionReportT, RepoT } from "../lib/api";

// Irreversible, so the dialog's job is to make the consequence legible BEFORE
// the confirmation is typed, not to warn after.
//
// The one thing a user most needs to know differs by repo: a cloned repo loses
// its directory, a locally-registered one does not and its files are left
// exactly where they are. Saying which, up front and specifically, is what stops
// someone hesitating over a delete that was never going to touch their work --
// or worse, assuming a clone's files are safe because a local repo's were.
//
// The backend enforces this independently (deletion.py checks source_kind AND
// containment in the clone cache); this only tells the truth about what the
// backend will do. A dialog is not a guard.

function label(repo: RepoT): string {
  return repo.owner ? `${repo.owner}/${repo.name}` : repo.name;
}

export function DeleteRepoDialog({
  repo, onClose, onDeleted,
}: {
  repo: RepoT;
  onClose: () => void;
  onDeleted: (report: RepoDeletionReportT) => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<RepoDeletionReportT | null>(null);

  const expected = label(repo);
  const isClone = repo.source_kind === "clone";
  const matches = typed.trim() === expected;

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api<RepoDeletionReportT>(`/api/repos/${repo.id}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm: typed.trim() }),
      });
      setReport(result);
      onDeleted(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // createPortal into document.body, following SlideOver -- and here it is
  // load-bearing rather than tidy. This dialog is rendered from inside a
  // RepoCard, which is itself a clickable `cursor-pointer` card. Inline, the
  // card's own subtree won hit-testing over the fixed overlay: a browser pass
  // found the confirm button visible, enabled, and UNCLICKABLE, with playwright
  // reporting `<div class="flex items-start justify-between gap-3"> … intercepts
  // pointer events`. A portal escapes the card's stacking context entirely.
  //
  // z-50 sits above `.chrome` (the fixed top nav), which also intercepted.
  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-ink/80 flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label={`Delete ${expected}`}
    >
      <div className="card p-5 w-full max-w-lg space-y-4" onClick={(e) => e.stopPropagation()}>
        {/* --- the report, once it exists: shown, never swallowed --------- */}
        {report ? (
          <>
            <h2 className="font-display text-lg text-snow">Deleted {report.label}</h2>
            <div className="space-y-1 font-mono text-[11px]">
              {Object.entries(report.rows_deleted).map(([table, n]) => (
                <div key={table} className="flex justify-between gap-4">
                  <span className="text-fog">{table}</span>
                  <span className="text-snow/85 tabular-nums">{n.toLocaleString()}</span>
                </div>
              ))}
              <div className="flex justify-between gap-4 border-t border-line pt-1 mt-1">
                <span className="text-fog">total rows</span>
                <span className="text-snow tabular-nums">{report.rows_total.toLocaleString()}</span>
              </div>
            </div>
            <p className="font-mono text-[11px] text-fog leading-relaxed">
              {report.directory_reason}
            </p>
            <button onClick={onClose} className="btn-accent w-full">Close</button>
          </>
        ) : (
          <>
            <h2 className="font-display text-lg text-danger">Delete {expected}?</h2>

            {/* The consequence, stated before the confirmation field rather
                than beside the button. */}
            <div className="space-y-2 text-[12px] leading-relaxed">
              <p className="text-snow/85">
                This removes every analysis row for this repo — files, symbols, imports, rankings,
                clusters, health snapshots and job history. It cannot be undone.
              </p>
              {isClone ? (
                <p className="text-warning">
                  Athena cloned this repo, so its clone directory will also be deleted from disk.
                  Nothing outside Athena's own cache is touched.
                </p>
              ) : (
                <p className="text-accent">
                  This repo is registered from a directory you own, so{" "}
                  <span className="font-medium">no files on disk will be touched</span>. Only Athena's
                  database rows are removed.
                </p>
              )}
              {repo.local_path && (
                <p className="font-mono text-[10px] text-fog break-all">{repo.local_path}</p>
              )}
            </div>

            <label className="block space-y-1">
              <span className="font-mono text-[10px] uppercase tracking-widest text-fog">
                Type <span className="text-snow">{expected}</span> to confirm
              </span>
              <input
                autoFocus
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && matches && !busy) submit(); }}
                placeholder={expected}
                className="w-full bg-transparent border border-line rounded px-2 py-1.5 text-snow text-sm font-mono"
              />
            </label>

            {error && <p className="text-danger text-xs break-words">{error}</p>}

            <div className="flex gap-2">
              <button onClick={onClose} disabled={busy} className="btn-ghost flex-1">Cancel</button>
              <button
                onClick={submit}
                disabled={!matches || busy}
                className="btn-accent flex-1 disabled:opacity-40"
              >
                {busy ? "Deleting…" : "Delete permanently"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
