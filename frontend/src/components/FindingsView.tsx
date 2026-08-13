import { useState } from "react";
import { api, FindingsFilesT, FindingsResponseT, FindingsRowT } from "../lib/api";
import { isUnexposed, shapeFindings, TOP_N } from "../lib/findingsQueue";

// Phase L: health markers as pickable work rather than a list of findings.
//
// The queue is keyed on (marker x directory), not on files. apache/superset
// produces 6,649 findings across 3,520 files, and 81.4% of those files carry
// exactly ONE finding even after the most aggressive cut -- so a per-file list
// cannot be ordered by finding count, and a fifth of it ties at zero exposure
// too. "cycle_participation in superset/views, 40 files" is a piece of work; a
// file with one marker on it is a row in the file tree.
//
// See backend/app/services/codebase/findings_queue.py for the aggregation, the
// adaptive directory roll-up, and why churn multiplies rather than listing.

function rowKey(r: FindingsRowT): string {
  return `${r.marker}::${r.directory}`;
}

function ChurnPip({ mean }: { mean: number }) {
  // Churn is the ordering weight, shown so the weighting is visible rather
  // than folded invisibly into the score. Three bands, because a continuous
  // bar here would imply a precision the mean of a severity does not carry.
  if (mean < 0.15) return null;
  const high = mean >= 0.6;
  return (
    <span
      title={`Mean churn ${mean.toFixed(2)} — this area changes often, which weights its score up`}
      className={`font-mono text-[10px] px-1 rounded ${
        high ? "bg-warning/15 text-warning" : "bg-fog/10 text-fog"
      }`}
    >
      {high ? "high churn" : "churn"}
    </span>
  );
}

function QueueRow({
  row, expanded, members, loading, onToggle, onSelectFile,
}: {
  row: FindingsRowT;
  expanded: boolean;
  members: FindingsFilesT | null;
  loading: boolean;
  onToggle: () => void;
  onSelectFile: (fileId: number) => void;
}) {
  const unexposed = isUnexposed(row);
  return (
    <div className={`card p-3 border-l-2 ${unexposed ? "border-l-line" : "border-l-accent"}`}>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-display text-sm text-snow">{row.label}</span>
        <span className="font-mono text-[11px] text-fog break-all">{row.directory}</span>
      </div>

      <div className="flex items-center gap-2 mt-1 flex-wrap">
        <span className="font-mono text-[10px] text-fog">{row.file_count} files</span>
        <span className="font-mono text-[10px] text-fog">·</span>
        <span className={`font-mono text-[10px] ${unexposed ? "text-fog" : "text-accent"}`}>
          score {row.score.toFixed(2)}
        </span>
        <ChurnPip mean={row.churn_mean} />
        {row.irreducible && (
          <span
            title="Every file in this row is in one directory, so no row-size limit divides it further."
            className="font-mono text-[10px] px-1 rounded bg-fog/10 text-fog"
          >
            single directory — not further divisible by path
          </span>
        )}
      </div>

      {unexposed && (
        // A zero score is a statement, not a missing value: nothing depends on
        // these files and they do not change. Said plainly, because "score
        // 0.00" next to a real finding otherwise reads as a bug.
        <p className="text-fog text-[11px] mt-1.5 leading-relaxed">
          Nothing imports these files and they have no recorded churn, so this scores zero and sorts
          last. The findings are real; their exposure is not.
        </p>
      )}

      <button onClick={onToggle} className="font-mono text-[10px] text-fog hover:text-accent mt-1.5">
        {loading ? "loading…" : expanded ? "− hide files" : "+ show files"}
      </button>

      {expanded && members && (
        <ul className="mt-1 space-y-0.5 border-t border-line pt-2 max-h-56 overflow-y-auto">
          {/* Clickable through to Focus, the same wiring Matrix, the reading
              list and Dependency Clusters use. A queue whose rows cannot be
              opened is a report, not a queue. */}
          {members.files.map((f) => (
            <li key={f.file_id} className="flex items-baseline gap-2">
              <button
                onClick={() => onSelectFile(f.file_id)}
                title={`Open ${f.path} in Focus`}
                className="flex-1 text-left font-mono text-[10px] text-fog break-all hover:text-accent transition-colors"
              >
                {f.path}
              </button>
              <span className="font-mono text-[10px] text-fog shrink-0">
                {f.severity.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FindingsView({
  repoId, data, loading, onReload, onSelectFile,
}: {
  repoId: string;
  data: FindingsResponseT | null;
  loading: boolean;
  onReload: () => void;
  onSelectFile: (fileId: number) => void;
}) {
  const [markerFilter, setMarkerFilter] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showBelowFloor, setShowBelowFloor] = useState(false);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [memberCache, setMemberCache] = useState<Record<string, FindingsFilesT>>({});
  const [loadingMembers, setLoadingMembers] = useState(false);

  const { rows, visible, findings, markers, irreducibleRows } =
    shapeFindings(data?.rows, markerFilter, showAll);

  const handleToggle = async (row: FindingsRowT) => {
    const key = rowKey(row);
    if (expandedKey === key) {
      setExpandedKey(null);
      return;
    }
    setExpandedKey(key);
    if (memberCache[key]) return;
    setLoadingMembers(true);
    try {
      // The floor and cap are passed back because the split is a pure function
      // of (snapshot, floor, max_files) -- sending different ones would return
      // the members of a row that was never displayed.
      const params = new URLSearchParams({
        marker: row.marker,
        directory: row.directory,
        floor: String(data?.floor ?? ""),
        max_files: String(data?.max_files_per_row ?? ""),
      });
      const res = await api<FindingsFilesT>(`/api/repos/${repoId}/findings/files?${params}`);
      setMemberCache((c) => ({ ...c, [key]: res }));
    } catch {
      setExpandedKey(null);
    } finally {
      setLoadingMembers(false);
    }
  };

  if (!data) {
    return (
      <div className="card p-6 text-center">
        <p className="text-fog text-sm">
          {loading ? "Loading findings…" : "No code-health snapshot for this repo yet."}
        </p>
        {!loading && (
          <button onClick={onReload} className="btn-ghost mt-3 font-mono text-xs">
            retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="card p-3">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-display text-sm text-snow">
            {rows.length} {rows.length === 1 ? "row" : "rows"}
          </span>
          <span className="font-mono text-[11px] text-fog">
            {findings.toLocaleString()} findings shown
          </span>
          {/* The hidden count is stated, not implied. A floor a user cannot see
              is indistinguishable from a tool that missed something. */}
          {data.hidden_below_floor > 0 && (
            <button
              onClick={() => setShowBelowFloor((v) => !v)}
              className="font-mono text-[11px] text-fog hover:text-accent underline decoration-dotted"
              title={`Findings below severity ${data.floor} are hidden by default`}
            >
              {data.hidden_below_floor.toLocaleString()} below threshold
            </button>
          )}
        </div>

        {showBelowFloor && (
          <p className="text-fog text-[11px] mt-2 leading-relaxed">
            {data.hidden_below_floor.toLocaleString()} findings sit below severity{" "}
            {data.floor} and are hidden by default — they are markers that barely fired, and in a
            work queue they are noise. Nothing is deleted: raise or drop the floor with the{" "}
            <span className="font-mono">floor</span> parameter to see them.
          </p>
        )}

        <p className="text-fog text-[11px] mt-2 leading-relaxed">
          Rows are one marker in one area, sorted by severity × exposure × churn. Churn is a weight
          on the other findings, not a finding of its own — {data.churn_weighted_files.toLocaleString()}{" "}
          files carry one.
          {irreducibleRows > 0 && (
            <>
              {" "}
              {irreducibleRows} {irreducibleRows === 1 ? "row is" : "rows are"} a single directory and
              cannot be divided further by path.
            </>
          )}
        </p>

        {data.staleness?.stale && (
          <p className="text-warning text-[11px] mt-2 leading-relaxed">
            {data.staleness.detail ?? "This snapshot no longer describes the repo as it is now."}
          </p>
        )}
      </div>

      {markers.length > 1 && (
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setMarkerFilter(null)}
            className={`font-mono text-[10px] px-2 py-1 rounded transition-colors ${
              markerFilter === null ? "bg-accent/15 text-accent" : "text-fog hover:text-snow"
            }`}
          >
            all markers
          </button>
          {markers.map((m) => (
            <button
              key={m.marker}
              onClick={() => setMarkerFilter(m.marker === markerFilter ? null : m.marker)}
              className={`font-mono text-[10px] px-2 py-1 rounded transition-colors ${
                markerFilter === m.marker ? "bg-accent/15 text-accent" : "text-fog hover:text-snow"
              }`}
            >
              {m.label} ({m.count})
            </button>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {visible.map((r) => {
          const key = rowKey(r);
          return (
            <QueueRow
              key={key}
              row={r}
              expanded={expandedKey === key}
              members={memberCache[key] ?? null}
              loading={loadingMembers && expandedKey === key}
              onToggle={() => handleToggle(r)}
              onSelectFile={onSelectFile}
            />
          );
        })}
      </div>

      {rows.length > TOP_N && (
        <button onClick={() => setShowAll((v) => !v)} className="btn-ghost font-mono text-xs">
          {showAll ? `show top ${TOP_N}` : `show all ${rows.length}`}
        </button>
      )}

      {rows.length === 0 && (
        <div className="card p-6 text-center">
          <p className="text-fog text-sm">No findings above the threshold for this filter.</p>
        </div>
      )}
    </div>
  );
}
