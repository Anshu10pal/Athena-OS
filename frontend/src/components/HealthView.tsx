import { useState } from "react";
import {
  api, HealthAxisT, HealthCoverageT, HealthFileT, HealthFilesResponseT,
  HealthResponseT, timeAgo,
} from "../lib/api";

// Phase 1 code health: deliberately an EVIDENCE/STATUS view, not a
// three-healthy-numbers scorecard.
//
// On our own repos this currently renders Architecture Health at ~10.0 with
// zero file-level cycles found, and Change Hotspot N/A on two of three repos.
// A conventional scorecard would present that as "all green", which would be
// actively misleading: the score is high because the file-level contract is
// narrow, not because the architecture was examined and found sound -- and
// the same product shows the user directory-level cycles on another tab.
//
// So every axis here leads with what was measured and what was not. Scope,
// N/A reasons and resolution limits are primary content, not footnotes.

const AXIS_META: Record<string, { label: string; scale: string; direction: string }> = {
  maintainability: {
    label: "Maintainability",
    scale: "1–10",
    direction: "higher is better",
  },
  architecture_health: {
    label: "Architecture Health",
    scale: "1–10",
    direction: "higher is better",
  },
  change_hotspot: {
    label: "Change Hotspot",
    scale: "0–9 exposure",
    direction: "higher means review sooner",
  },
};

function bandColor(value: number, higherIsBetter: boolean): string {
  const good = higherIsBetter ? value >= 7 : value <= 2;
  const mid = higherIsBetter ? value >= 4.5 : value <= 5;
  if (good) return "text-accent";
  if (mid) return "text-warning";
  return "text-danger";
}

/** The mandatory Architecture Health scope block. Rendered beside the score,
 *  never behind a tooltip -- a high score on a narrow contract otherwise
 *  reads as "the architecture is healthy". */
function CoverageBlock({
  coverage, onGoToClusters,
}: {
  coverage: HealthCoverageT;
  onGoToClusters: () => void;
}) {
  return (
    <div className="border border-line rounded-lg p-3.5 space-y-2 bg-glass">
      <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">What this covers</p>
      <dl className="space-y-1.5 font-mono text-[11px]">
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-fog">Static file-graph evidence</dt>
          <dd className="text-snow/85 tabular-nums shrink-0">
            {coverage.file_level_cycle_count} file-level cycles
          </dd>
        </div>
        {coverage.directory_cycle_count !== null && (
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-fog">Directory cycles, observed separately</dt>
            <dd className="shrink-0">
              <button
                onClick={onGoToClusters}
                className="text-info hover:text-accent underline underline-offset-2 tabular-nums"
                title="These are NOT part of this score — see Dependency Clusters"
              >
                {coverage.directory_cycle_count}
              </button>
            </dd>
          </div>
        )}
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-fog">Active markers</dt>
          <dd className="text-snow/85 text-right shrink-0">
            {coverage.active_markers.length ? coverage.active_markers.join(", ") : "none"}
          </dd>
        </div>
        {/* Each inactive marker keeps its own reason. "Measured and found
            nothing" is a result; "never computed" is a gap. Showing them as
            one list would let a coverage gap read as a clean bill. */}
        {coverage.inactive_markers.map((m) => (
          <div key={m.key} className="flex items-baseline justify-between gap-3">
            <dt className="text-fog/70">{m.key}</dt>
            <dd
              className={
                "text-right shrink-0 " +
                (m.state === "no_input" ? "text-warning" : "text-fog/60")
              }
              title={m.detail}
            >
              {m.state === "no_input"
                ? "not computed"
                : m.state === "not_applicable"
                ? "n/a here"
                : "found nothing"}
            </dd>
          </div>
        ))}
      </dl>
      <ul className="pt-1.5 border-t border-line/60 space-y-1">
        {coverage.limitations.map((l) => (
          <li key={l} className="font-mono text-[10px] text-fog/70 leading-relaxed">— {l}</li>
        ))}
      </ul>
    </div>
  );
}

function NaReasons({ axis }: { axis: HealthAxisT }) {
  const reasons = Object.entries(axis.na_reasons ?? {}).sort((a, b) => b[1] - a[1]);
  if (!reasons.length) return null;
  return (
    <ul className="space-y-1">
      {reasons.map(([reason, n]) => (
        <li key={reason} className="font-mono text-[10px] text-fog/70 leading-relaxed">
          <span className="text-fog">{n} file{n === 1 ? "" : "s"}</span> — {reason}
        </li>
      ))}
    </ul>
  );
}

function AxisCard({
  axisKey, axis, onGoToClusters,
}: {
  axisKey: string;
  axis: HealthAxisT;
  onGoToClusters: () => void;
}) {
  const meta = AXIS_META[axisKey];
  const higherIsBetter = axisKey !== "change_hotspot";
  const hasValue = axis.mean !== undefined && axis.mean !== null;
  const isHotspot = axisKey === "change_hotspot";

  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-2 flex-wrap">
          <h4 className="font-display text-lg text-snow/85">{meta.label}</h4>
          {isHotspot && (
            <span className="font-mono text-[9px] uppercase tracking-widest text-warning border border-warning/50 rounded px-1.5 py-0.5">
              uncalibrated
            </span>
          )}
        </div>
        <span className="font-mono text-[10px] text-fog/60">
          {meta.scale} · {meta.direction}
        </span>
      </div>

      {hasValue ? (
        <div className="flex items-baseline gap-3">
          <span className={`font-display text-4xl tabular-nums ${bandColor(axis.mean!, higherIsBetter)}`}>
            {axis.mean!.toFixed(2)}
          </span>
          <span className="font-mono text-[10px] text-fog/70">
            median {axis.median?.toFixed(2)} · p10 {axis.p10?.toFixed(2)} · {axis.scored} files
          </span>
        </div>
      ) : (
        // Never an empty or grey zero: absence of measurement is not a
        // measurement of zero.
        <p className="font-mono text-sm text-warning">
          N/A — insufficient usable history
        </p>
      )}

      {axis.resolution_limited && (
        <p className="font-mono text-[10px] text-warning leading-relaxed border-l-2 border-warning/50 pl-2.5">
          Limited history resolution — this ranks files, but the magnitude is low-resolution.
          Use it to order review, not to judge how much more exposed one file is than another.
        </p>
      )}

      {axis.na > 0 && (
        <div className="space-y-1.5 pt-1">
          <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">
            Not measured ({axis.na})
          </p>
          <NaReasons axis={axis} />
        </div>
      )}

      {axis.coverage && (
        <CoverageBlock coverage={axis.coverage} onGoToClusters={onGoToClusters} />
      )}
    </div>
  );
}

function MarkerBreakdown({ file }: { file: HealthFileT }) {
  const maint = file.explanation?.maintainability;
  if (!maint) return null;
  const markers = maint.markers ?? [];
  return (
    <div className="px-4 pb-3 space-y-1">
      {markers.map((m) => (
        <div key={m.key} className="flex items-baseline justify-between gap-3 font-mono text-[10px]">
          <span className={m.available ? "text-fog" : "text-fog/50"}>{m.label}</span>
          <span className="shrink-0 tabular-nums">
            {!m.available ? (
              <span className="text-fog/50" title={m.na_reason ?? ""}>N/A</span>
            ) : m.deduction > 0 ? (
              <span className="text-warning">
                {m.raw_value} → −{m.deduction.toFixed(2)}
              </span>
            ) : (
              <span className="text-fog/50">{m.raw_value} · clear</span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

export function HealthView({
  repoId, data, onCompute, computing, onSelectFile, onGoToClusters,
}: {
  repoId: string;
  data: HealthResponseT | null;
  onCompute: () => void;
  computing: boolean;
  onSelectFile: (fileId: number) => void;
  onGoToClusters: () => void;
}) {
  const [files, setFiles] = useState<HealthFilesResponseT | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [sort, setSort] = useState("maintainability");

  const loadFiles = async (nextSort: string) => {
    setSort(nextSort);
    try {
      setFiles(await api<HealthFilesResponseT>(
        `/api/repos/${repoId}/health/files?sort=${nextSort}&limit=25`));
    } catch {
      setFiles(null);
    }
  };

  if (!data) {
    return (
      <div className="space-y-4">
        <button className="btn-accent disabled:opacity-50" disabled={computing} onClick={onCompute}>
          {computing ? "Analysing…" : "Run code health analysis"}
        </button>
        <p className="text-fog text-sm font-mono">
          No snapshot yet. This measures structure from the parsed AST, the import graph and git
          history — no code leaves this machine and no model is called.
        </p>
      </div>
    );
  }

  const { snapshot, axes, trend } = data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-secondary disabled:opacity-50" disabled={computing} onClick={onCompute}>
          {computing ? "Analysing…" : "Refresh analysis"}
        </button>
        <span className="font-mono text-[10px] text-fog/70">
          {snapshot.files_scored} scored · {snapshot.files_na} N/A · {timeAgo(snapshot.computed_at)}
        </span>
      </div>

      {/* Provenance is primary, not a footnote: for a local repo the live
          working tree is analysed, so HEAD alone can misdescribe the bytes. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-fog/70">
        <span>branch <span className="text-snow/80">{snapshot.branch || "—"}</span></span>
        {snapshot.head_sha && (
          <span>sha <span className="text-snow/80">{snapshot.head_sha.slice(0, 8)}</span></span>
        )}
        {snapshot.working_tree_dirty && (
          <span className="text-warning">uncommitted changes were included in this analysis</span>
        )}
        <span>
          analyzer v{snapshot.analyzer_version} · thresholds v{snapshot.thresholds_version} ·
          weights v{snapshot.weights_version}
        </span>
      </div>

      {/* Never a zero baseline. */}
      <div className="card p-3.5">
        {trend.comparable ? (
          <div className="flex flex-wrap items-center gap-4 font-mono text-[11px]">
            <span className="text-fog/70 uppercase tracking-widest text-[10px]">Since last snapshot</span>
            {Object.entries(trend.deltas).map(([axis, delta]) => (
              <span key={axis} className="text-fog">
                {AXIS_META[axis]?.label ?? axis}{" "}
                <span className={delta === 0 ? "text-fog/60" : delta > 0 ? "text-accent" : "text-danger"}>
                  {delta > 0 ? "+" : ""}{delta.toFixed(2)}
                </span>
              </span>
            ))}
          </div>
        ) : (
          <p className="font-mono text-[11px] text-fog">
            {trend.reason === "No previous snapshot on this branch."
              ? "One comparable snapshot recorded; trend appears after the next changed analysis."
              : trend.reason}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {["maintainability", "architecture_health", "change_hotspot"].map((key) =>
          axes[key] ? (
            <AxisCard key={key} axisKey={key} axis={axes[key]} onGoToClusters={onGoToClusters} />
          ) : null
        )}
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-fog">Files</span>
          {[
            { key: "maintainability", label: "Least maintainable" },
            { key: "adjusted_exposure", label: "Exposure / 100 LOC" },
            { key: "exposure", label: "Raw exposure" },
          ].map((o) => (
            <button
              key={o.key}
              onClick={() => loadFiles(o.key)}
              className={
                "font-mono text-[10px] rounded-full px-2.5 py-1 border transition-colors " +
                (files && sort === o.key
                  ? "border-accent/50 text-accent"
                  : "border-line text-fog hover:text-snow")
              }
            >
              {o.label}
            </button>
          ))}
        </div>

        {files && (
          <div className="card divide-y divide-line/60">
            {files.files.length === 0 ? (
              <p className="p-4 font-mono text-[11px] text-fog">
                No files rankable by this measure — {files.excluded_na} were N/A and are excluded
                rather than ranked as zero.
              </p>
            ) : (
              files.files.map((f) => (
                <div key={f.file_id}>
                  <div className="flex items-center gap-3 px-4 py-2.5">
                    <button
                      onClick={() => onSelectFile(f.file_id)}
                      className="font-mono text-xs text-snow/85 hover:text-accent flex-1 min-w-0 truncate text-left"
                    >
                      {f.path}
                    </button>
                    <span className="font-mono text-[10px] text-fog/70 shrink-0 tabular-nums">
                      {f.maintainability !== null && <>M {f.maintainability.toFixed(1)}</>}
                      {f.exposure !== null && <> · exp {f.exposure.toFixed(2)}</>}
                      {f.adjusted_exposure !== null && (
                        <> · {f.adjusted_exposure.toFixed(2)}/100LOC</>
                      )}
                    </span>
                    <button
                      onClick={() => setExpanded(expanded === f.file_id ? null : f.file_id)}
                      className="font-mono text-[10px] text-fog hover:text-accent shrink-0"
                    >
                      {expanded === f.file_id ? "−" : "+"}
                    </button>
                  </div>
                  {expanded === f.file_id && <MarkerBreakdown file={f} />}
                </div>
              ))
            )}
            {files.files.length > 0 && files.excluded_na > 0 && (
              <p className="px-4 py-2 font-mono text-[10px] text-fog/70">
                {files.excluded_na} file(s) N/A for this measure — excluded from ranking, not scored zero.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
