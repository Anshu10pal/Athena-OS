import { useRef, useState } from "react";
import { HealthAxisMarkerT, HealthAxisT, HealthResponseT } from "../lib/api";
import {
  aggregateBand, aggregateHealth, AxisTileT, buildAxisTiles, HOTSPOT_AXIS,
} from "../lib/healthAggregate";
import { SlideOver } from "./SlideOver";

// The Overview's health section: one aggregate tile out of 100 plus each axis
// on its own, each opening an insights panel.
//
// The aggregate exists as a product decision that departs from the contract's
// "three separate axes, no blended score". The compensating requirement is
// that the blend can never hide its own composition: the tile always states
// how many axes it is based on, an excluded axis says why on its own face,
// and the panel behind it lists the composition before anything else.

const BAND_CLASS = {
  good: "text-accent",
  mixed: "text-warning",
  poor: "text-danger",
} as const;

function Tile({
  label, value, sub, tone, onClick, muted,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: string;
  onClick: () => void;
  muted?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className="card p-4 text-left hover:border-accent/40 transition-colors group w-full"
    >
      <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">{label}</p>
      <p className={`font-display text-3xl tabular-nums mt-1.5 ${muted ? "text-fog/60" : tone ?? "text-snow/90"}`}>
        {value}
      </p>
      <p className="font-mono text-[10px] text-fog/70 mt-1 leading-relaxed">{sub}</p>
      <p className="font-mono text-[9px] uppercase tracking-widest text-fog/40 mt-2 group-hover:text-accent transition-colors">
        details →
      </p>
    </button>
  );
}

function MarkerLine({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 font-mono text-[11px] py-1">
      <span className="text-fog">{label}</span>
      <span className="text-snow/80 text-right shrink-0">{detail}</span>
    </div>
  );
}

function AggregateInsights({
  tiles, data,
}: {
  tiles: AxisTileT[];
  data: HealthResponseT | null;
}) {
  const agg = aggregateHealth(tiles);
  return (
    <div className="space-y-4 text-sm">
      <p className="text-fog leading-relaxed">
        A mean of the structural axes below, each rescaled from 1–10 onto 10–100.
        It is a convenience summary, not a validated measure: the underlying
        thresholds are reasoned defaults, not fitted to any outcome on this
        repository.
      </p>

      <div className="border border-line rounded-lg p-3.5 space-y-1">
        <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70 mb-1.5">
          What went into it
        </p>
        {tiles.map((t) => (
          <MarkerLine
            key={t.key}
            label={t.label}
            detail={
              t.includedInAggregate
                ? `${t.outOf100}/100 — included`
                : t.available
                ? "measured, excluded"
                : "not measurable"
            }
          />
        ))}
      </div>

      {/* The single most misreadable thing about a blended number: which
          parts of it are actually present. */}
      <p className="font-mono text-[11px] text-fog leading-relaxed">
        Based on {agg.axesUsed} of {agg.axesPossible} structural axes.
        {agg.partial && " An axis that could not be measured is excluded from the mean entirely — not counted as zero, and not counted as full marks."}
      </p>

      <p className="font-mono text-[11px] text-warning leading-relaxed border-l-2 border-warning/50 pl-3">
        Change Hotspot is deliberately not in this number. It ranks what to
        review first, where higher means worse — the opposite direction to the
        health axes. Averaging them would require inverting one, and the result
        would answer no question.
      </p>

      {data?.snapshot && (
        <p className="font-mono text-[10px] text-fog/60 leading-relaxed">
          analyzer v{data.snapshot.analyzer_version} · thresholds v
          {data.snapshot.thresholds_version} · weights v{data.snapshot.weights_version}
          {data.snapshot.working_tree_dirty && " · uncommitted changes were included"}
        </p>
      )}
    </div>
  );
}

/** What the axis actually considered. Shows the threshold and weight applied
 *  alongside real contribution -- fire rate alone cannot distinguish a marker
 *  that fires often and contributes nothing from one that dominates its
 *  category, which is why mean deduction sits beside it. */
function MarkersConsidered({
  markers, caps,
}: {
  markers: HealthAxisMarkerT[];
  caps?: Record<string, number>;
}) {
  const byCategory: Record<string, HealthAxisMarkerT[]> = {};
  for (const m of markers) (byCategory[m.category] ??= []).push(m);

  const stateLabel = (m: HealthAxisMarkerT) =>
    m.state === "fired"
      ? `${m.fired}/${m.evaluated} files`
      : m.state === "no_input"
      ? "not computed"
      : m.state === "not_applicable"
      ? "n/a here"
      : "found nothing";

  return (
    <div className="space-y-3">
      <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">
        Parameters considered
      </p>
      {Object.entries(byCategory).map(([category, group]) => (
        <div key={category} className="border border-line rounded-lg p-3">
          <p className="font-mono text-[10px] uppercase tracking-widest text-fog/60 mb-2">
            {category}
            {caps?.[category] !== undefined && (
              <span className="text-fog/40"> · cap {caps[category].toFixed(1)}</span>
            )}
          </p>
          <div className="space-y-2">
            {group.map((m) => (
              <div key={m.key} className="space-y-0.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-[11px] text-snow/85">{m.label}</span>
                  <span
                    className={
                      "font-mono text-[10px] shrink-0 " +
                      (m.state === "fired"
                        ? "text-warning"
                        : m.state === "no_input"
                        ? "text-danger"
                        : "text-fog/50")
                    }
                  >
                    {stateLabel(m)}
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-3 font-mono text-[10px] text-fog/60">
                  <span>
                    weight {m.weight.toFixed(1)}
                    {m.warn !== null && (
                      <> · fires above {m.warn}
                        {m.saturate !== null && <> · maxes at {m.saturate}</>}
                      </>
                    )}
                  </span>
                  {m.mean_deduction !== null && (
                    <span className="shrink-0 tabular-nums">
                      avg −{m.mean_deduction.toFixed(2)}
                      {m.max_deduction ? ` · worst −${m.max_deduction.toFixed(2)}` : ""}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      <p className="font-mono text-[10px] text-fog/60 leading-relaxed">
        Each parameter scales from 0 at its "fires above" value to its full weight at
        "maxes at", and a category cannot deduct more than its cap. Thresholds are
        reasoned defaults, not fitted to any outcome on this repository.
      </p>
    </div>
  );
}

function AxisInsights({ tile, axis }: { tile: AxisTileT; axis: HealthAxisT | undefined }) {
  const coverage = axis?.coverage;
  return (
    <div className="space-y-4 text-sm">
      {!tile.available ? (
        <p className="font-mono text-sm text-warning leading-relaxed">
          Not measurable for this repo{tile.naReason ? ` — ${tile.naReason}` : "."}
        </p>
      ) : (
        <div className="flex items-baseline gap-3">
          <span className="font-display text-3xl tabular-nums text-snow/90">
            {tile.value!.toFixed(2)}
          </span>
          <span className="font-mono text-[11px] text-fog/70">
            {tile.direction === "higher_is_better"
              ? "1–10 · higher is better"
              : "0–9 exposure · higher means review sooner"}
          </span>
        </div>
      )}

      {axis && axis.mean !== undefined && (
        <div className="border border-line rounded-lg p-3.5">
          <MarkerLine label="Median" detail={axis.median?.toFixed(2) ?? "—"} />
          <MarkerLine label="Worst decile (p10)" detail={axis.p10?.toFixed(2) ?? "—"} />
          <MarkerLine label="Files scored" detail={String(axis.scored)} />
          <MarkerLine label="Not measured" detail={String(axis.na)} />
        </div>
      )}

      {tile.resolutionLimited && (
        <p className="font-mono text-[11px] text-warning leading-relaxed border-l-2 border-warning/50 pl-3">
          Limited history resolution — this orders files for review, but the
          magnitude is low-resolution. Use it to decide what to read first, not
          how much worse one file is than another.
        </p>
      )}

      {tile.exclusionReason && (
        <p className="font-mono text-[11px] text-fog leading-relaxed border-l-2 border-line pl-3">
          Not part of the aggregate: {tile.exclusionReason}
        </p>
      )}

      {axis && axis.na > 0 && (
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">
            Why files were not measured
          </p>
          {Object.entries(axis.na_reasons ?? {})
            .sort((a, b) => b[1] - a[1])
            .map(([reason, n]) => (
              <p key={reason} className="font-mono text-[10px] text-fog/70 leading-relaxed">
                <span className="text-fog">{n} file{n === 1 ? "" : "s"}</span> — {reason}
              </p>
            ))}
        </div>
      )}

      {axis?.markers && axis.markers.length > 0 && (
        <MarkersConsidered markers={axis.markers} caps={axis.category_caps} />
      )}

      {/* The Architecture scope block, carried as API data so a score can
          never be shown without what it applies to. */}
      {coverage && (
        <div className="border border-line rounded-lg p-3.5 space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70 mb-1.5">
            What this covers
          </p>
          <MarkerLine
            label="Static file-graph evidence"
            detail={`${coverage.file_level_cycle_count} file-level cycles`}
          />
          {coverage.directory_cycle_count !== null && (
            <MarkerLine
              label="Directory cycles, observed separately"
              detail={`${coverage.directory_cycle_count} — see Dependency Clusters`}
            />
          )}
          <MarkerLine
            label="Active markers"
            detail={coverage.active_markers.join(", ") || "none"}
          />
          {coverage.inactive_markers.map((m) => (
            <MarkerLine
              key={m.key}
              label={m.key}
              detail={
                m.state === "no_input"
                  ? "not computed"
                  : m.state === "not_applicable"
                  ? "n/a here"
                  : "found nothing"
              }
            />
          ))}
          <ul className="pt-2 mt-1 border-t border-line/60 space-y-1">
            {coverage.limitations.map((l) => (
              <li key={l} className="font-mono text-[10px] text-fog/70 leading-relaxed">— {l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function HealthTiles({
  data, onCompute, computing,
}: {
  data: HealthResponseT | null;
  onCompute: () => void;
  computing: boolean;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const triggerRef = useRef<HTMLDivElement>(null);

  const tiles = buildAxisTiles(data);
  const agg = aggregateHealth(tiles);

  if (!data) {
    return (
      <section className="space-y-3" ref={triggerRef}>
        <h3 className="font-display text-xl text-snow/85">Code health</h3>
        <div className="card p-5 flex flex-wrap items-center gap-4">
          <button className="btn-accent disabled:opacity-50" disabled={computing} onClick={onCompute}>
            {computing ? "Analysing…" : "Run code health analysis"}
          </button>
          <p className="font-mono text-[11px] text-fog leading-relaxed max-w-xl">
            Measures structure from the parsed AST, the import graph and git history.
            No code leaves this machine and no model is called.
          </p>
        </div>
      </section>
    );
  }

  const openTile = tiles.find((t) => t.key === openKey);
  // Tolerated as optional: a snapshot served by an older backend has no
  // staleness field, and absent evidence of staleness is not evidence of
  // freshness -- but nor is it grounds for marking a good snapshot stale.
  const stale = data.staleness?.stale === true;

  return (
    <section className="space-y-3" ref={triggerRef}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="font-display text-xl text-snow/85">Code health</h3>
        <button
          className="font-mono text-[10px] uppercase tracking-widest text-fog hover:text-accent disabled:opacity-50"
          disabled={computing}
          onClick={onCompute}
        >
          {computing ? "analysing…" : "refresh"}
        </button>
      </div>

      {stale && (
        <div className="card p-3.5 border-warning/40 bg-warning/[0.06]">
          <p className="font-mono text-[10px] uppercase tracking-widest text-warning/90">
            Out of date — describes an earlier state of this repo
          </p>
          <p className="font-mono text-[11px] text-fog leading-relaxed mt-1.5">
            {data.staleness.detail}
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile
          label="Code health"
          value={agg.score === null ? "N/A" : `${agg.score}`}
          // A stale score keeps its number but loses its colour. The band is a
          // verdict on the repo as it is now, and a green 97 beside a Contents
          // panel reading 0 files is the exact misread this whole surface is
          // built to avoid.
          tone={agg.score === null || stale ? undefined : BAND_CLASS[aggregateBand(agg.score)]}
          muted={agg.score === null || stale}
          sub={
            agg.score === null
              ? "nothing measurable to aggregate"
              : `out of 100 · ${agg.axesUsed} of ${agg.axesPossible} axes${agg.partial ? " · partial" : ""}${stale ? " · out of date" : ""}`
          }
          onClick={() => setOpenKey("__aggregate__")}
        />
        {tiles.map((t) => (
          <Tile
            key={t.key}
            label={t.label}
            value={
              !t.available
                ? "N/A"
                : t.key === HOTSPOT_AXIS
                ? t.value!.toFixed(2)
                : `${t.outOf100}`
            }
            muted={!t.available || stale}
            sub={
              !t.available
                ? "not measurable"
                : t.key === HOTSPOT_AXIS
                ? `0–9 exposure${t.resolutionLimited ? " · low resolution" : ""}${stale ? " · out of date" : ""}`
                : `out of 100${stale ? " · out of date" : ""}`
            }
            onClick={() => setOpenKey(t.key)}
          />
        ))}
      </div>

      <SlideOver
        open={openKey !== null}
        onClose={() => setOpenKey(null)}
        triggerRef={triggerRef}
        title={openKey === "__aggregate__" ? "Code health" : openTile?.label ?? ""}
      >
        {openKey === "__aggregate__" ? (
          <AggregateInsights tiles={tiles} data={data} />
        ) : openTile ? (
          <AxisInsights tile={openTile} axis={data.axes[openTile.key]} />
        ) : null}
      </SlideOver>
    </section>
  );
}
