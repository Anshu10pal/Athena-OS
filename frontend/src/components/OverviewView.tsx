import { HealthFactorT, OverviewT, timeAgo } from "../lib/api";

// Phase K1: the repo landing page. Exists because RepoDetail had grown to
// seven analysis tabs sharing one filter bar, so opening a repo dropped
// you straight into a 173-row ranked table with no orientation -- what is
// this repo, how big, how healthy, where are the risky parts. This answers
// those first and sends you to the analysis views deliberately rather than
// by default.
//
// Every number here comes from the /overview endpoint, which reads only
// what ingest/rank/clustering already persisted. Nothing on this page is
// computed client-side, and nothing is estimated.

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}

// Bands, not a pass/fail line. A single threshold would imply this score
// is calibrated against some external standard; it isn't -- it is a
// weighted mean of five measured structural factors, so the honest visual
// is "roughly where this sits", not a verdict.
function bandColor(score: number): string {
  if (score >= 0.7) return "text-accent";
  if (score >= 0.45) return "text-warning";
  return "text-danger";
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

function FactorRow({ factor }: { factor: HealthFactorT }) {
  const unavailable = !factor.available || factor.value === null;
  return (
    <div className="py-3 border-b border-line/60 last:border-b-0">
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-mono text-xs text-snow/85">{factor.label}</p>
        <div className="flex items-baseline gap-3 shrink-0">
          <span className="font-mono text-[10px] text-fog/60">weight {pct(factor.weight)}</span>
          {unavailable ? (
            <span className="font-mono text-[10px] uppercase tracking-widest text-fog/60">not measurable</span>
          ) : (
            <span className={`font-mono text-sm tabular-nums ${bandColor(factor.value!)}`}>
              {pct(factor.value!)}
            </span>
          )}
        </div>
      </div>
      {!unavailable && (
        <div className="mt-2 h-1 rounded-full bg-line overflow-hidden">
          <div
            className="h-full rounded-full bg-accent/60"
            style={{ width: `${Math.round(factor.value! * 100)}%` }}
          />
        </div>
      )}
      <p className="font-mono text-[10px] text-fog/70 leading-relaxed mt-2">{factor.detail}</p>
    </div>
  );
}

export function OverviewView({
  data, onSelectFile, onGoToView,
}: {
  data: OverviewT;
  onSelectFile: (fileId: number) => void;
  onGoToView: (view: "reading" | "depgraph" | "architecture" | "layers" | "subsystems") => void;
}) {
  const { repo, counts, health, hotspots } = data;
  const languages = Object.entries(counts.languages).sort((a, b) => b[1] - a[1]);

  const JUMP: { view: "reading" | "depgraph" | "architecture" | "layers" | "subsystems"; label: string; hint: string }[] = [
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
            {repo.source_kind} · {repo.host}
          </span>
        </div>
        {repo.description ? (
          <p className="text-fog text-sm leading-relaxed max-w-3xl">
            {repo.description}
            <span className="font-mono text-[10px] text-fog/50 ml-2">from {repo.description_source}</span>
          </p>
        ) : (
          // Never synthesised. A repo with no packaging metadata and no
          // README genuinely has no self-description.
          <p className="text-fog/60 text-sm font-mono">
            No description found — this repo has no package.json/pyproject description and no README prose.
          </p>
        )}
        <p className="font-mono text-[10px] text-fog/60">
          Last ingested {timeAgo(repo.last_ingested_at)}
          {repo.last_ingested_sha && <> · {repo.last_ingested_sha.slice(0, 8)}</>}
        </p>
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <h3 className="font-display text-xl text-snow/85">Code health</h3>
          <span className="font-mono text-[10px] text-fog/60">
            {health.factors_used} of {health.factors_total} factors measurable
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr] gap-4">
          <div className="card p-5 flex flex-col items-center justify-center">
            {health.score === null ? (
              <p className="font-mono text-xs text-fog/70 text-center">Not enough data yet — run ingest and rank.</p>
            ) : (
              <>
                <p className={`font-display text-5xl tabular-nums ${bandColor(health.score)}`}>
                  {Math.round(health.score * 100)}
                </p>
                <p className="font-mono text-[10px] uppercase tracking-widest text-fog/60 mt-1">structural</p>
              </>
            )}
          </div>
          <div className="card px-5 py-1">
            {health.factors.map((f) => <FactorRow key={f.key} factor={f} />)}
          </div>
        </div>

        {/* Carried straight from the backend payload rather than written
            here, so the UI cannot drift from what the score actually is. */}
        <p className="font-mono text-[10px] text-fog/70 leading-relaxed max-w-3xl border-l-2 border-line pl-3">
          {health.caveat}
        </p>
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-xl text-snow/85">Contents</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <Stat label="Files" value={compact(counts.files)} sub={`${counts.test_files} test files`} />
          <Stat label="Lines" value={compact(counts.lines)} />
          <Stat label="Modules" value={compact(counts.directories)} sub="directories" />
          <Stat
            label="Symbols"
            value={compact(counts.symbols_total)}
            sub={Object.entries(counts.symbol_kinds).map(([k, v]) => `${v} ${k}`).join(" · ")}
          />
          <Stat
            label="Imports"
            value={compact(counts.imports_total)}
            sub={`${pct(counts.import_resolution_rate)} resolved`}
          />
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
        <h3 className="font-display text-xl text-snow/85">Change hotspots</h3>
        {/* Deliberately NOT "files producing the most bugs". This system
            has no defect data; a hotspot is a churn x fan-in risk proxy,
            and saying otherwise would be an overclaim of exactly the kind
            this project's ESLint validation rounds corrected twice. */}
        <p className="font-mono text-[10px] text-fog/70 leading-relaxed max-w-3xl">
          Files that change often <em className="not-italic text-fog">and</em> are heavily depended on — the product
          of both, since either alone is unremarkable. This is a risk proxy, not measured defects: no defect or
          issue-tracker data exists in this system.
        </p>

        {!hotspots.available ? (
          <p className="card p-4 font-mono text-[11px] text-warning leading-relaxed">{hotspots.reason}</p>
        ) : (
          <div className="card divide-y divide-line/60">
            {hotspots.files.map((f, i) => (
              <button
                key={f.file_id}
                onClick={() => onSelectFile(f.file_id)}
                className="w-full flex items-center gap-4 px-4 py-2.5 text-left hover:bg-glass transition-colors"
              >
                <span className="font-mono text-[10px] text-fog/50 w-5 shrink-0 tabular-nums">{i + 1}</span>
                <span className="font-mono text-xs text-snow/85 flex-1 min-w-0 truncate">{f.path}</span>
                <span className="font-mono text-[10px] text-fog/70 shrink-0 tabular-nums">
                  {f.commit_count} commits · {f.fan_in} importers
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-xl text-snow/85">Analyse</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {JUMP.map((j) => (
            <button
              key={j.view}
              onClick={() => onGoToView(j.view)}
              className="card p-4 text-left hover:border-accent/40 transition-colors group"
            >
              <p className="font-mono text-xs text-snow/85 group-hover:text-accent transition-colors">{j.label}</p>
              <p className="font-mono text-[10px] text-fog/70 mt-1">{j.hint}</p>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
