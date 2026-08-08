import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, RepoJobT, RepoT, streamJobProgress, timeAgo } from "../lib/api";

function AddRepoForm({ onAdded }: { onAdded: (repo: RepoT) => void }) {
  const [mode, setMode] = useState<"url" | "local_path">("url");
  const [value, setValue] = useState("");
  const [sourceRoot, setSourceRoot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!value.trim()) return;
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, string> = { [mode]: value.trim() };
      if (sourceRoot.trim()) payload.source_root = sourceRoot.trim();
      const repo = await api<RepoT>("/api/repos", { method: "POST", body: JSON.stringify(payload) });
      onAdded(repo);
      setValue("");
      setSourceRoot("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card p-5 space-y-3">
      <h3 className="font-display text-sm text-fog">Register a repository</h3>
      <div className="flex gap-2 font-mono text-[10px] uppercase tracking-widest">
        <button
          className={`px-2.5 py-1 rounded border ${mode === "url" ? "border-accent text-accent" : "border-line text-fog"}`}
          onClick={() => setMode("url")}
        >
          Git URL
        </button>
        <button
          className={`px-2.5 py-1 rounded border ${mode === "local_path" ? "border-accent text-accent" : "border-line text-fog"}`}
          onClick={() => setMode("local_path")}
        >
          Local path
        </button>
      </div>
      <input
        className="input"
        placeholder={mode === "url" ? "https://github.com/owner/repo.git" : "D:\\path\\to\\repo"}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && !busy && submit()}
      />
      <input
        className="input"
        placeholder="Source root (optional -- subdirectory to scope ingestion to)"
        value={sourceRoot}
        onChange={(e) => setSourceRoot(e.target.value)}
      />
      {error && <p className="text-danger text-sm">{error}</p>}
      <button className="btn-accent disabled:opacity-50" disabled={busy || !value.trim()} onClick={submit}>
        {busy ? "Adding…" : "Add repo"}
      </button>
    </div>
  );
}

function RepoCard({ repo, onOpen, onChanged }: { repo: RepoT; onOpen: () => void; onChanged: (r: RepoT) => void }) {
  const [job, setJob] = useState<RepoJobT | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const sync = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setRunning(true);
    setError("");
    try {
      const { job_id } = await api<{ job_id: number }>(`/api/repos/${repo.id}/jobs`, { method: "POST" });
      await streamJobProgress(repo.id, job_id, (evt) => {
        if (evt.type === "progress") {
          setJob((j) => ({
            ...(j as RepoJobT),
            status: evt.status as RepoJobT["status"],
            stage: evt.stage,
            progress_current: evt.current,
            progress_total: evt.total,
            message: evt.message,
          }));
        } else if (evt.type === "done") {
          setRunning(false);
          api<RepoT[]>("/api/repos").then((repos) => {
            const updated = repos.find((r) => r.id === repo.id);
            if (updated) onChanged(updated);
          });
        } else if (evt.type === "error") {
          setRunning(false);
          setError(evt.message);
        }
      });
    } catch (e: any) {
      setRunning(false);
      setError(e.message);
    }
  };

  return (
    <div className="card p-4 cursor-pointer hover:border-accent/40 transition-colors" onClick={onOpen}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-snow truncate">
            {repo.owner ? `${repo.owner}/${repo.name}` : repo.name}
          </p>
          <p className="font-mono text-[10px] text-fog mt-1">
            {repo.source_kind} · {repo.host}
            {repo.source_root ? ` · ${repo.source_root}` : ""}
          </p>
        </div>
        <button
          className="btn-secondary shrink-0 !text-xs !py-1.5 disabled:opacity-50"
          disabled={running}
          onClick={sync}
        >
          {running ? "Syncing…" : "Sync & Rank"}
        </button>
      </div>

      <div className="flex gap-2 mt-3 flex-wrap font-mono text-[10px]">
        <span className="text-fog border border-line rounded px-1.5 py-0.5">
          {repo.file_count ?? "?"} files
        </span>
        <span className="text-fog border border-line rounded px-1.5 py-0.5">
          synced {timeAgo(repo.last_ingested_at)}
        </span>
        {repo.last_ingested_sha && (
          <span className="text-fog border border-line rounded px-1.5 py-0.5">
            {repo.last_ingested_sha.slice(0, 7)}
          </span>
        )}
      </div>

      {running && job && (
        <p className="font-mono text-[10px] text-accent mt-2 animate-pulse">
          {job.stage}
          {job.progress_total > 0 ? ` (${job.progress_current}/${job.progress_total})` : ""} — {job.message}
        </p>
      )}
      {error && <p className="text-danger text-xs mt-2">{error}</p>}
    </div>
  );
}

export default function Repos() {
  const [repos, setRepos] = useState<RepoT[]>([]);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const load = () =>
    api<RepoT[]>("/api/repos")
      .then(setRepos)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="w-full max-w-none space-y-6">
      <div>
        <h2 className="font-display text-2xl font-semibold">Codebase Agent</h2>
        <p className="text-fog text-sm mt-1">
          Register a repository, then sync it to get a ranked reading list of its most important files --
          no summaries, no graph, just what to read first.
        </p>
      </div>

      <AddRepoForm onAdded={(r) => setRepos((rs) => [r, ...rs])} />

      {error && <p className="text-danger text-sm">{error}</p>}

      <div className="space-y-3">
        {repos.length === 0 && !error && (
          <p className="text-fog text-sm font-mono">No repositories registered yet.</p>
        )}
        {repos.map((r) => (
          <RepoCard
            key={r.id}
            repo={r}
            onOpen={() => navigate(`/repos/${r.id}`)}
            onChanged={(updated) => setRepos((rs) => rs.map((x) => (x.id === updated.id ? updated : x)))}
          />
        ))}
      </div>
    </div>
  );
}
