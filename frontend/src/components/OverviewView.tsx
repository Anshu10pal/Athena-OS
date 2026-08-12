import { HealthDirectoriesT, HealthResponseT, OverviewT, timeAgo } from "../lib/api";
import { HealthDetail } from "./HealthDetail";
import { HealthTiles } from "./HealthTiles";

// The repo overview is orientation, and now carries the code-health tiles
// directly rather than sending the reader to a separate tab. The aggregate
// out of 100 is a product decision that departs from the contract's
// "three separate axes, no blended score" -- see lib/healthAggregate.ts for
// what that blend does and does not include, and why the Change Hotspot axis
// is shown beside it but never folded into it.

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-4">
      <p className="font-mono text-[10px] uppercase tracking-widest text-fog/70">{label}</p>
      <p className="font-display text-2xl text-snow/90 mt-1.5 tabular-nums">{value}</p>
      {sub && <p className="font-mono text-[10px] text-fog/70 mt-1">{sub}</p>}
    </div>
  );
}

type OverviewViewT = "reading" | "depgraph" | "architecture" | "layers" | "subsystems";

export function OverviewView({
  data, health, directories, onComputeHealth, computingHealth, onSelectFile, onGoToView,
}: {
  data: OverviewT;
  health: HealthResponseT | null;
  directories: HealthDirectoriesT | null;
  onComputeHealth: () => void;
  computingHealth: boolean;
  onSelectFile: (fileId: number) => void;
  onGoToView: (view: OverviewViewT) => void;
}) {
  const { repo, counts, hotspots } = data;
  const languages = Object.entries(counts.languages).sort((a, b) => b[1] - a[1]);

  const jumpTargets: { view: OverviewViewT; label: string; hint: string }[] = [
    { view: "reading", label: "Reading list", hint: "Ranked order to read this repo in" },
    { view: "architecture", label: "Architecture", hint: "Directory-level map" },
    { view: "depgraph", label: "Dependency Graph", hint: "Explore one file's neighbourhood" },
    { view: "layers", label: "Layers", hint: "Distance from the entry points" },
    { view: "subsystems", label: "Dependency Clusters", hint: "Groups that import each other densely" },
  ];

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="font-display text-3xl text-snow/90 tracking-tight">
            {repo.owner ? `${repo.owner}/` : ""}{repo.name}
          </h2>
          <span className="font-mono text-[10px] uppercase tracking-widest text-fog/60">
            {repo.source_kind} - {repo.host}
          </span>
        </div>
        {repo.description ? (
          <p className="text-fog text-sm leading-relaxed max-w-3xl">
            {repo.description}
            <span className="font-mono text-[10px] text-fog/50 ml-2">from {repo.description_source}</span>
          </p>
        ) : (
          <p className="text-fog/60 text-sm font-mono">
            No description found - this repo has no package.json/pyproject description and no README prose.
          </p>
        )}
        <p className="font-mono text-[10px] text-fog/60">
          Last ingested {timeAgo(repo.last_ingested_at)}
          {repo.last_ingested_sha && <> - {repo.last_ingested_sha.slice(0, 8)}</>}
        </p>
      </section>

      <HealthTiles
        data={health}
        onCompute={onComputeHealth}
        computing={computingHealth}
      />

      {/* Directly under the tiles on purpose: the tiles give the number, this
          gives the location. Anywhere else and the reader has to hold one in
          their head while they find the other. */}
      {health && <HealthDetail data={directories} />}

      <section className="space-y-3">
        <h3 className="font-display text-xl text-snow/85">Contents</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <Stat label="Files" value={compact(counts.files)} sub={`${counts.test_files} test files`} />
          <Stat label="Lines" value={compact(counts.lines)} />
          <Stat label="Modules" value={compact(counts.directories)} sub="directories" />
          <Stat
            label="Symbols"
            value={compact(counts.symbols_total)}
            sub={Object.entries(counts.symbol_kinds).map(([k, v]) => `${v} ${k}`).join(" - ")}
          />
          <Stat label="Imports" value={compact(counts.imports_total)} sub={`${pct(counts.import_resolution_rate)} resolved`} />
          <Stat label="Clusters" value={compact(data.cluster_count)} sub="modularity" />
        </div>
        <div className="flex flex-wrap gap-2">
          {languages.map(([lang, n]) => (
            <span key={lang} className="font-mono text-[10px] rounded-full border border-line px-2.5 py-1 text-fog/80">
              {lang} <span className="text-fog/50">{n}</span>
            </span>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-xl text-snow/85">Change-impact watchlist</h3>
        <p className="font-mono text-[10px] text-fog/70 leading-relaxed max-w-3xl">
          Files that change often and have many importers. This is a change-impact signal, not a defect prediction.
        </p>
        {!hotspots.available ? (
          <p className="card p-4 font-mono text-[11px] text-warning leading-relaxed">{hotspots.reason}</p>
        ) : (
          <div className="card divide-y divide-line/60">
            {hotspots.files.map((file, index) => (
              <button
                key={file.file_id}
                onClick={() => onSelectFile(file.file_id)}
                className="w-full flex items-center gap-4 px-4 py-2.5 text-left hover:bg-glass transition-colors"
              >
                <span className="font-mono text-[10px] text-fog/50 w-5 shrink-0 tabular-nums">{index + 1}</span>
                <span className="font-mono text-xs text-snow/85 flex-1 min-w-0 truncate">{file.path}</span>
                <span className="font-mono text-[10px] text-fog/70 shrink-0 tabular-nums">
                  {file.commit_count} commits - {file.fan_in} importers
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-xl text-snow/85">Analyse</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {jumpTargets.map((target) => (
            <button
              key={target.view}
              onClick={() => onGoToView(target.view)}
              className="card p-4 text-left hover:border-accent/40 transition-colors group"
            >
              <p className="font-mono text-xs text-snow/85 group-hover:text-accent transition-colors">{target.label}</p>
              <p className="font-mono text-[10px] text-fog/70 mt-1">{target.hint}</p>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
