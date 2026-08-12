import { useState } from "react";
import { HealthDirectoriesT } from "../lib/api";
import {
  DirRowT,
  ROLLUP_AXES,
  RollupAxisKeyT,
  axisMeta,
  bandOf,
  barFraction,
  compactNloc,
  hotCohortSentence,
  rankDirectories,
} from "../lib/healthRollup";

// Where the headline number comes from. The tiles above say "94"; this says
// which part of the repo is carrying it.
//
// Two things this view refuses to do, both of which a directory table normally
// does by default: it never shows an average without the count behind it, and
// it never silently drops a directory that was measured but held back from the
// ranking for sample size. Both would read as "nothing to see here" when the
// truth is "not enough to rank".

const BAR = {
  good: "bg-accent/70",
  mixed: "bg-warning/70",
  poor: "bg-danger/75",
} as const;

const TEXT = {
  good: "text-accent",
  mixed: "text-warning",
  poor: "text-danger",
} as const;

function Row({
  row, axisKey, expanded, onToggle,
}: {
  row: DirRowT;
  axisKey: RollupAxisKeyT;
  expanded: boolean;
  onToggle: () => void;
}) {
  const band = bandOf(row.value, axisKey);
  const fill = barFraction(row.value, axisKey);
  // Size sets the bar's presence, not its length: 4k NLOC at 6.95 is a bigger
  // problem than 200 NLOC at the same score, and the eye should get that
  // without reading the numbers.
  const weight = Math.min(1, 0.35 + row.nloc / 6000);

  return (
    <div className="border-b border-line/60 last:border-b-0">
      <button
        onClick={onToggle}
        className="w-full text-left py-2.5 px-1 hover:bg-snow/[0.02] transition-colors group"
      >
        <div className="flex items-center gap-3">
          <span className="font-mono text-[11px] text-snow/85 truncate flex-1" title={row.path}>
            {row.label}
          </span>
          <div className="hidden sm:block w-24 h-1.5 rounded-full bg-snow/[0.06] overflow-hidden shrink-0">
            <div
              className={`h-full rounded-full ${BAR[band]}`}
              style={{ width: `${Math.max(fill * 100, 3)}%`, opacity: weight }}
            />
          </div>
          <span className={`font-mono text-[11px] tabular-nums w-10 text-right shrink-0 ${TEXT[band]}`}>
            {row.value.toFixed(2)}
          </span>
          <span className="font-mono text-[10px] text-fog/60 tabular-nums w-16 text-right shrink-0">
            {row.filesScored} file{row.filesScored === 1 ? "" : "s"}
          </span>
          <span className="font-mono text-[10px] text-fog/50 tabular-nums w-12 text-right shrink-0 hidden md:inline">
            {compactNloc(row.nloc)}
          </span>
          <span className="font-mono text-[10px] text-fog/40 shrink-0 group-hover:text-accent transition-colors">
            {expanded ? "−" : "+"}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="px-1 pb-3 space-y-1.5 font-mono text-[10px]">
          <p className="text-fog/70 break-all">{row.path}</p>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-fog/70">
            <span>
              weighted <span className="text-snow/80 tabular-nums">{row.value.toFixed(2)}</span>
            </span>
            {row.unweighted !== null && (
              <span>
                unweighted <span className="text-snow/80 tabular-nums">{row.unweighted.toFixed(2)}</span>
              </span>
            )}
            <span>
              scored <span className="text-snow/80 tabular-nums">{row.filesScored}</span>
            </span>
            {row.filesNa > 0 && (
              <span>
                not measured <span className="text-snow/80 tabular-nums">{row.filesNa}</span>
              </span>
            )}
          </div>
          {/* The gap between the two means is the signal that one large file
              dominates -- which is exactly what the reader needs to know next. */}
          {row.unweighted !== null && Math.abs(row.unweighted - row.value) > 0.5 && (
            <p className="text-fog/60 leading-relaxed">
              Weighted by size, this scores {Math.abs(row.unweighted - row.value).toFixed(2)}{" "}
              {row.value < row.unweighted ? "lower" : "higher"} than a plain average — one large
              file is carrying it.
            </p>
          )}
          {row.worstPath && row.worst !== null && (
            <p className="text-fog/70 break-all">
              worst · <span className="text-snow/80">{row.worstPath}</span>{" "}
              <span className="tabular-nums">{row.worst.toFixed(2)}</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function HealthDetail({ data }: { data: HealthDirectoriesT | null }) {
  const [axisKey, setAxisKey] = useState<RollupAxisKeyT>("maintainability");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showUnrankable, setShowUnrankable] = useState(false);

  if (!data) return null;

  const { ranked, unrankable } = rankDirectories(data, axisKey);
  const cohort = data.hot_cohort;
  const sentence = hotCohortSentence(data);
  const visible = showAll ? ranked : ranked.slice(0, 6);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="font-display text-xl text-snow/85">Health detail</h3>
        {/* The lens recolours and re-sorts the same rows rather than replacing
            the view, so switching axis keeps the reader's place. */}
        <div className="flex items-center gap-1">
          {ROLLUP_AXES.map((a) => (
            <button
              key={a.key}
              onClick={() => setAxisKey(a.key)}
              className={
                "font-mono text-[10px] uppercase tracking-widest px-2 py-1 rounded transition-colors " +
                (a.key === axisKey
                  ? "text-accent bg-accent/10"
                  : "text-fog/60 hover:text-snow/80")
              }
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card p-4 space-y-4">
        {/* --- the code in motion --- */}
        <div className="space-y-1.5">
          {sentence ? (
            <>
              <p className="text-sm text-snow/85 leading-relaxed">{sentence}</p>
              <p className="font-mono text-[10px] text-fog/70">
                {cohort.hot_files} of {cohort.baseline_files} files with history
                {cohort.churn_threshold !== null && <> · {cohort.churn_threshold}+ commits</>}
              </p>
              {cohort.caveat && (
                <p className="font-mono text-[10px] text-warning/85 leading-relaxed">
                  {cohort.caveat}
                </p>
              )}
              <p className="font-mono text-[10px] text-fog/55 leading-relaxed">
                {cohort.axis_note}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-fog leading-relaxed">
                Change-cohort comparison not available for this repo.
              </p>
              {cohort.na_reason && (
                <p className="font-mono text-[10px] text-fog/70 leading-relaxed">
                  {cohort.na_reason}
                </p>
              )}
            </>
          )}
        </div>

        {/* --- weakest directories --- */}
        <div className="pt-1 border-t border-line">
          <div className="flex items-baseline justify-between gap-3 mt-3 mb-1">
            <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">
              {axisMeta(axisKey).higherIsWorse ? "Highest exposure" : "Weakest"} directories
            </p>
            <p className="font-mono text-[10px] text-fog/50">weighted by size</p>
          </div>

          {ranked.length === 0 ? (
            <p className="font-mono text-[11px] text-fog/70 py-3 leading-relaxed">
              No directory has {data.min_files_to_rank} or more scored files on this axis, so
              nothing can be ranked. Individual files are still scored.
            </p>
          ) : (
            <div>
              {visible.map((row) => (
                <Row
                  key={row.path}
                  row={row}
                  axisKey={axisKey}
                  expanded={expanded === row.path}
                  onToggle={() => setExpanded(expanded === row.path ? null : row.path)}
                />
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2.5">
            {ranked.length > 6 && (
              <button
                onClick={() => setShowAll(!showAll)}
                className="font-mono text-[10px] text-fog/70 hover:text-accent transition-colors"
              >
                {showAll ? "▴ show fewer" : `▾ ${ranked.length - 6} more directories`}
              </button>
            )}
            {unrankable.length > 0 && (
              <button
                onClick={() => setShowUnrankable(!showUnrankable)}
                className="font-mono text-[10px] text-fog/70 hover:text-accent transition-colors"
              >
                {showUnrankable ? "▴ hide" : `▾ ${unrankable.length} not ranked`}
              </button>
            )}
          </div>

          {showUnrankable && (
            <div className="mt-2 pt-2 border-t border-line/60">
              <p className="font-mono text-[10px] text-fog/60 leading-relaxed mb-1.5">
                Measured, but held back from the ranking: fewer than {data.min_files_to_rank}{" "}
                scored files, so one unusual file would decide the position.
              </p>
              {unrankable.map((row) => (
                <Row
                  key={row.path}
                  row={row}
                  axisKey={axisKey}
                  expanded={expanded === row.path}
                  onToggle={() => setExpanded(expanded === row.path ? null : row.path)}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
