import { useState } from "react";
import {
  api,
  CycleCoherenceEntryT,
  SubsystemAlgorithmT,
  SubsystemMembersResponseT,
  SubsystemsResponseT,
  SubsystemT,
} from "../lib/api";

// Phase I1 (extended I6): modularity/Louvain are two independent
// clustering algorithms over the resolved import graph; on this repo they
// agree 100% (see the agreement banner below), so there is deliberately
// no disagreement-surfacing UI here yet -- that waits until a repo where
// the two clusterings actually diverge. HDBSCAN is a third, genuinely
// different signal -- density clustering over FastEmbed embeddings of
// symbol text, comparing itself against modularity rather than running
// alongside it (see subsystems.py's module docstring for the full
// reasoning). Reporting the agreement numbers themselves is the finding
// this phase ships, same as I1.
const ALGORITHMS: { value: SubsystemAlgorithmT; label: string }[] = [
  { value: "modularity", label: "Modularity" },
  { value: "louvain", label: "Louvain" },
  { value: "hdbscan", label: "HDBSCAN" },
];

function labelFor(s: SubsystemT): string {
  if (s.custom_label) return s.custom_label;
  if (s.active_label_rule === "top_fan_in") return s.top_fan_in_label;
  if (s.dominant_prefix_label) return s.dominant_prefix_label;
  return `Cluster ${s.cluster_index}`;
}

function CycleFinding({ entry }: { entry: CycleCoherenceEntryT }) {
  const pct = Math.round(entry.coherence * 100);
  return (
    <div className={`card p-3 border-l-2 ${entry.weak ? "border-l-warning" : "border-l-accent"}`}>
      <p className="font-mono text-xs text-snow">
        {entry.directories.join(" ⇄ ")}
        <span className={`ml-2 font-mono text-[10px] ${entry.weak ? "text-warning" : "text-accent"}`}>
          {pct}% coherent
        </span>
      </p>
      <p className="text-fog text-[11px] mt-1.5 leading-relaxed">
        {entry.weak ? (
          <>
            This is a cycle at the directory level, but only {entry.majority_count} of {entry.total_files} files
            actually landed in one dependency cluster. The cycle may be carried by a small number of specific edges
            between specific files, not by pervasive coupling across both directories -- worth checking whether
            inverting one or two of those edges resolves it, rather than restructuring either directory as a whole.
          </>
        ) : (
          <>
            {entry.majority_count} of {entry.total_files} files across these directories landed in one dependency
            cluster -- the cycle is carried by real, pervasive coupling, not a handful of edges.
          </>
        )}
      </p>
    </div>
  );
}

function SubsystemCard({
  repoId, subsystem, expanded, members, loadingMembers, onSelect, onToggleExpand, onRenamed,
}: {
  repoId: string;
  subsystem: SubsystemT;
  expanded: boolean;
  members: SubsystemMembersResponseT | null;
  loadingMembers: boolean;
  onSelect: (id: number) => void;
  onToggleExpand: (id: number) => void;
  onRenamed: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(labelFor(subsystem));
  const [saving, setSaving] = useState(false);

  const ruleNote = subsystem.custom_label
    ? "renamed by you"
    : subsystem.active_label_rule === "top_fan_in"
    ? "named after its highest-fan-in file"
    : `named after its most common directory (${subsystem.dominant_prefix_count}/${subsystem.member_count} members)`;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api(`/api/repos/${repoId}/subsystems/${subsystem.id}`, {
        method: "PATCH",
        body: JSON.stringify({ custom_label: draft }),
      });
      onRenamed();
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        {editing ? (
          <form className="flex-1 flex gap-2" onSubmit={save}>
            <input
              type="text"
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="bg-transparent border border-line rounded px-2 py-1 text-snow text-sm font-mono flex-1 min-w-0"
            />
            <button type="submit" disabled={saving} className="font-mono text-[10px] text-accent disabled:opacity-50">
              {saving ? "saving…" : "save"}
            </button>
            <button type="button" onClick={() => setEditing(false)} className="font-mono text-[10px] text-fog">
              cancel
            </button>
          </form>
        ) : (
          <button
            onClick={() => onSelect(subsystem.id)}
            className="font-display text-sm text-snow hover:text-accent text-left"
            title="View this cluster's files in the Reading list"
          >
            {labelFor(subsystem)}
          </button>
        )}
        {!editing && (
          <button
            onClick={() => {
              setDraft(labelFor(subsystem));
              setEditing(true);
            }}
            className="font-mono text-[10px] text-fog hover:text-snow shrink-0"
          >
            rename
          </button>
        )}
      </div>
      <p className="font-mono text-[10px] text-fog">{subsystem.member_count} files · {ruleNote}</p>
      <button onClick={() => onToggleExpand(subsystem.id)} className="font-mono text-[10px] text-fog hover:text-accent">
        {loadingMembers ? "loading…" : expanded ? "− hide files" : "+ show files"}
      </button>
      {expanded && members && (
        <ul className="mt-1 space-y-0.5 border-t border-line pt-2 max-h-40 overflow-y-auto">
          {members.files.map((f) => (
            <li key={f.id} className="font-mono text-[10px] text-fog break-all">
              {f.path}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SubsystemsView({
  repoId, algorithm, onAlgorithmChange, data, onCompute, computing, onSelectSubsystem, onDataChanged,
}: {
  repoId: string;
  algorithm: SubsystemAlgorithmT;
  onAlgorithmChange: (a: SubsystemAlgorithmT) => void;
  data: SubsystemsResponseT | null;
  onCompute: () => void;
  computing: boolean;
  onSelectSubsystem: (id: number) => void;
  onDataChanged: () => void;
}) {
  const [memberCache, setMemberCache] = useState<Record<number, SubsystemMembersResponseT>>({});
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [loadingMembers, setLoadingMembers] = useState(false);

  const handleToggleExpand = async (id: number) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!memberCache[id]) {
      setLoadingMembers(true);
      try {
        const result = await api<SubsystemMembersResponseT>(`/api/repos/${repoId}/subsystems/${id}/members`);
        setMemberCache((m) => ({ ...m, [id]: result }));
      } finally {
        setLoadingMembers(false);
      }
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded border border-line p-1 gap-1">
          {ALGORITHMS.map((a) => (
            <button
              key={a.value}
              onClick={() => onAlgorithmChange(a.value)}
              className={
                "font-mono text-[10px] uppercase tracking-widest rounded px-3 py-1.5 transition-colors " +
                (algorithm === a.value ? "bg-accent/15 text-accent" : "text-fog hover:text-snow")
              }
            >
              {a.label}
            </button>
          ))}
        </div>
        <button className="btn-accent disabled:opacity-50" disabled={computing} onClick={onCompute}>
          {algorithm === "hdbscan"
            ? computing
              ? "Embedding files…"
              : "Cluster by Embeddings (HDBSCAN)"
            : computing
            ? "Detecting…"
            : "Detect Dependency Clusters"}
        </button>
        {data?.agreement !== null && data?.agreement !== undefined && (
          <span className="font-mono text-[10px] text-fog">
            {algorithm === "hdbscan" ? "HDBSCAN ⇄ Modularity agreement" : "Modularity ⇄ Louvain agreement"}:{" "}
            <span className="text-snow">{Math.round(data.agreement * 100)}%</span>
          </span>
        )}
      </div>

      <p className="text-fog text-[11px] font-mono leading-relaxed max-w-2xl">
        These are files that import each other more than they import the rest of the repo -- a measured coupling
        group, not a confirmed subsystem. Validated against eslint/eslint's own architecture doc: one cluster
        genuinely spanned five separately-named parts of the doc because they form a real call chain, not because
        the detector was wrong. Read a cluster as "these files are entangled," not as "this is one subsystem."
      </p>

      {algorithm === "hdbscan" && (
        <p className="text-fog text-[11px] font-mono leading-relaxed max-w-2xl">
          HDBSCAN groups files by what their code's symbol signatures and docstrings actually say, not by who
          imports whom -- a genuinely different signal from Modularity/Louvain above, run entirely locally
          (FastEmbed, no network call, nothing leaves this machine) and compared against Modularity's clustering
          rather than run alongside it. Embedding every file is real CPU work; the first run may also download a
          small local model if it isn't already cached.
        </p>
      )}

      {!data && (
        <p className="text-fog text-sm font-mono">
          Not yet computed -- click "{algorithm === "hdbscan" ? "Cluster by Embeddings (HDBSCAN)" : "Detect Dependency Clusters"}"
          to group this repo's files{algorithm === "hdbscan" ? " by what their code says it does" : " by import coupling"}.
        </p>
      )}

      {data && data.cycle_coherence && data.cycle_coherence.length > 0 && (
        <div className="space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-widest text-fog">Cycle-cluster coherence</p>
          {data.cycle_coherence.map((entry) => (
            <CycleFinding key={entry.directories.join("|")} entry={entry} />
          ))}
        </div>
      )}

      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {data.subsystems.map((s) => (
            <SubsystemCard
              key={s.id}
              repoId={repoId}
              subsystem={s}
              expanded={expandedId === s.id}
              members={memberCache[s.id] ?? null}
              loadingMembers={loadingMembers && expandedId === s.id}
              onSelect={onSelectSubsystem}
              onToggleExpand={handleToggleExpand}
              onRenamed={onDataChanged}
            />
          ))}
          {data.unclustered_count > 0 && (
            <div className="card p-4 space-y-1 border-dashed">
              <p className="font-display text-sm text-fog">Unclustered</p>
              <p className="font-mono text-[10px] text-fog">
                {data.unclustered_count} files{" "}
                {algorithm === "hdbscan"
                  ? "too far from any dense group of similar files (HDBSCAN's own \"noise\" points)"
                  : "with no edges dense enough to join any cluster"}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
