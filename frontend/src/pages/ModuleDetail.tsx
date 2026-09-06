import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CardPractice } from "../components/CardPractice";
import Toggle from "../components/Toggle";
import { api, getToken } from "../lib/api";
import { DecryptText } from "../lib/fx";
import { resourceLink } from "../lib/resourceLink";

interface Resource {
  id: number;
  kind: string;
  status: "intent" | "saved";
  title: string;
  url: string | null;
  search_query: string | null;
}

interface TopicT {
  id: number;
  title: string;
  blurb: string;
  estimated_minutes: number;
  done: boolean;
  resources: Resource[];
}

interface ModuleT {
  id: number;
  code_repo_id: number | null;
  slug: string;
  title: string;
  summary: string;
  kind: string;
  percent: number;
  state: "not_started" | "in_progress" | "complete";
  topic_count: number;
  total_minutes: number;
  topics: TopicT[];
}

// An uploaded resource has no `url` -- its bytes live behind an authenticated
// endpoint, GET /api/resources/{id}/file. A plain <a href> to that path 404s
// the auth check (the token lives in localStorage, not a cookie), so the
// click has to fetch with the bearer header and save the blob itself.
async function downloadFile(resource: Resource, onError: (message: string) => void) {
  try {
    const token = getToken();
    const res = await fetch(`/api/resources/${resource.id}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = resource.title;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e: any) {
    onError(e.message || "Download failed");
  }
}

function ResourceRow({
  resource,
  onSave,
  onDelete,
  onError,
}: {
  resource: Resource;
  onSave: (url: string, title: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState(resource.url || "");
  const [title, setTitle] = useState(resource.title || "");
  const [busy, setBusy] = useState(false);

  if (editing) {
    return (
      <div className="flex flex-wrap items-center gap-1.5 bg-panel2 border border-accent/40 rounded-lg px-2.5 py-2">
        <span className="font-mono text-[8px] uppercase text-fog shrink-0">{resource.kind}</span>
        <input
          className="input !py-1 !text-xs flex-1 min-w-[100px]"
          placeholder="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          className="input !py-1 !text-xs flex-1 min-w-[140px]"
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && url.trim() && !busy && document.getElementById(`save-${resource.id}`)?.click()}
        />
        <button
          id={`save-${resource.id}`}
          className="text-accent text-[10px] font-mono shrink-0 disabled:opacity-40"
          disabled={busy || !url.trim()}
          onClick={async () => {
            setBusy(true);
            try {
              await onSave(url.trim(), title.trim());
              setEditing(false);
            } finally {
              setBusy(false);
            }
          }}
        >
          save
        </button>
        <button
          className="text-fog hover:text-snow text-[10px] font-mono shrink-0"
          onClick={() => {
            setEditing(false);
            setUrl(resource.url || "");
            setTitle(resource.title || "");
          }}
        >
          cancel
        </button>
      </div>
    );
  }

  const link = resourceLink(resource);
  const linkClassName = `flex-1 min-w-0 flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition-colors ${
    link.action === "search"
      ? "border border-dashed border-line text-fog hover:text-accent hover:border-accent/40"
      : "bg-panel2 border border-accent/40 text-snow hover:border-accent"
  }`;
  const label = link.action === "search" ? `search: ${resource.title || resource.search_query}` : resource.title;

  return (
    <div className="flex items-center gap-1.5 group">
      {link.action === "download" ? (
        <button onClick={() => downloadFile(resource, onError)} className={linkClassName}>
          <span className="font-mono text-[8px] uppercase shrink-0">{resource.kind}</span>
          <span className="flex-1 truncate text-left">{label}</span>
        </button>
      ) : (
        <a href={link.href} target="_blank" rel="noreferrer" className={linkClassName}>
          <span className="font-mono text-[8px] uppercase shrink-0">{resource.kind}</span>
          <span className="flex-1 truncate">{label}</span>
        </a>
      )}
      <button
        onClick={() => setEditing(true)}
        className="text-fog hover:text-accent text-[10px] font-mono shrink-0 px-1 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
      >
        edit
      </button>
      <button
        onClick={onDelete}
        className="text-fog hover:text-danger text-[10px] font-mono shrink-0 px-1 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
        aria-label={`Delete resource "${resource.title}"`}
      >
        ✕
      </button>
    </div>
  );
}

function TopicCard({
  topic,
  onToggleDone,
  onResourceSave,
  onResourceDelete,
  onAddResource,
  onUpload,
  onUndo,
  onDeleteTopic,
  onResourceError,
}: {
  topic: TopicT;
  onToggleDone: (topicId: number, done: boolean) => void;
  onResourceSave: (resourceId: number, url: string, title: string) => Promise<void>;
  onResourceDelete: (resourceId: number) => Promise<void>;
  onAddResource: (topicId: number, kind: string, title: string, url: string) => Promise<void>;
  onUpload: (topicId: number, file: File) => Promise<void>;
  onUndo: (topicId: number) => Promise<void>;
  onDeleteTopic: (topicId: number) => Promise<void>;
  onResourceError: (message: string) => void;
}) {
  const [addingOpen, setAddingOpen] = useState(false);
  const [newKind, setNewKind] = useState("article");
  const [newTitle, setNewTitle] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="card p-4">
      <div className="flex items-start gap-3">
        <Toggle checked={topic.done} onChange={(v) => onToggleDone(topic.id, v)} label={`Mark "${topic.title}" complete`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <p className={`font-medium ${topic.done ? "text-fog line-through" : "text-snow"}`}>{topic.title}</p>
            <div className="flex gap-2.5 shrink-0 font-mono text-[9px]">
              <button onClick={() => onUndo(topic.id)} className="text-fog hover:text-accent">
                undo
              </button>
              <button
                onClick={() => window.confirm(`Remove topic "${topic.title}"? This deletes its resources too.`) && onDeleteTopic(topic.id)}
                className="text-fog hover:text-danger"
              >
                remove
              </button>
            </div>
          </div>
          <p className="text-fog text-sm mt-1">{topic.blurb}</p>
          <p className="font-mono text-[9px] text-fog mt-1.5">~{topic.estimated_minutes} min</p>

          <div className="mt-2.5 space-y-1.5">
            {topic.resources.map((r) => (
              <ResourceRow
                key={r.id}
                resource={r}
                onSave={(url, title) => onResourceSave(r.id, url, title)}
                onDelete={() => onResourceDelete(r.id)}
                onError={onResourceError}
              />
            ))}
          </div>

          {addingOpen ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <select
                className="input !py-1 !text-xs !w-auto"
                value={newKind}
                onChange={(e) => setNewKind(e.target.value)}
              >
                <option value="article">article</option>
                <option value="video">video</option>
                <option value="doc">doc</option>
              </select>
              <input
                className="input !py-1 !text-xs flex-1 min-w-[100px]"
                placeholder="Title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
              <input
                className="input !py-1 !text-xs flex-1 min-w-[140px]"
                placeholder="https://…"
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
              />
              <button
                className="text-accent text-[10px] font-mono disabled:opacity-40"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await onAddResource(topic.id, newKind, newTitle.trim(), newUrl.trim());
                    setAddingOpen(false);
                    setNewTitle("");
                    setNewUrl("");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                add
              </button>
              <button className="text-fog hover:text-snow text-[10px] font-mono" onClick={() => setAddingOpen(false)}>
                cancel
              </button>
            </div>
          ) : (
            <div className="mt-2 flex gap-3 font-mono text-[10px]">
              <button onClick={() => setAddingOpen(true)} className="text-fog hover:text-accent">
                + add link
              </button>
              <button onClick={() => fileRef.current?.click()} disabled={uploading} className="text-fog hover:text-accent disabled:opacity-40">
                {uploading ? "uploading…" : "+ upload file"}
              </button>
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                accept=".pdf,.docx,.pptx,.xlsx,.md,.txt"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  setUploading(true);
                  try {
                    await onUpload(topic.id, file);
                  } finally {
                    setUploading(false);
                  }
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ModuleDetail() {
  const { slug } = useParams<{ slug: string }>();
  const [params] = useSearchParams();
  const from = params.get("from");
  const navigate = useNavigate();
  const [module, setModule] = useState<ModuleT | null>(null);
  const [error, setError] = useState("");
  const [newTopicTitle, setNewTopicTitle] = useState("");

  const load = () =>
    api<ModuleT>(`/api/modules/${slug}`)
      .then(setModule)
      .catch((e) => setError(e.message));

  useEffect(() => {
    setModule(null);
    setError("");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const toggleTopic = async (topicId: number, done: boolean) => {
    if (!module) return;
    setModule({ ...module, topics: module.topics.map((t) => (t.id === topicId ? { ...t, done } : t)) });
    try {
      const progress = await api<{ percent: number; state: ModuleT["state"] }>(`/api/topics/${topicId}/progress`, {
        method: "PATCH",
        body: JSON.stringify({ done }),
      });
      setModule((m) => (m ? { ...m, percent: progress.percent, state: progress.state } : m));
    } catch {
      setModule((m) => (m ? { ...m, topics: m.topics.map((t) => (t.id === topicId ? { ...t, done: !done } : t)) } : m));
    }
  };

  const saveResource = async (resourceId: number, url: string, title: string) => {
    try {
      const updated = await api<Resource>(`/api/resources/${resourceId}`, {
        method: "PATCH",
        body: JSON.stringify({ url, title }),
      });
      setModule((m) =>
        m
          ? { ...m, topics: m.topics.map((t) => ({ ...t, resources: t.resources.map((r) => (r.id === resourceId ? updated : r)) })) }
          : m
      );
    } catch (e: any) {
      setError(e.message);
    }
  };

  const deleteResource = async (resourceId: number) => {
    try {
      await api(`/api/resources/${resourceId}`, { method: "DELETE" });
      setModule((m) =>
        m ? { ...m, topics: m.topics.map((t) => ({ ...t, resources: t.resources.filter((r) => r.id !== resourceId) })) } : m
      );
    } catch (e: any) {
      setError(e.message);
    }
  };

  const addResource = async (topicId: number, kind: string, title: string, url: string) => {
    try {
      const created = await api<Resource>(`/api/topics/${topicId}/resources`, {
        method: "POST",
        body: JSON.stringify({ kind, title, url: url || undefined }),
      });
      setModule((m) => (m ? { ...m, topics: m.topics.map((t) => (t.id === topicId ? { ...t, resources: [...t.resources, created] } : t)) } : m));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const uploadFile = async (topicId: number, file: File) => {
    try {
      const formData = new FormData();
      formData.append("file", file);
      const created = await api<Resource>(`/api/topics/${topicId}/resources/upload`, { method: "POST", body: formData });
      setModule((m) => (m ? { ...m, topics: m.topics.map((t) => (t.id === topicId ? { ...t, resources: [...t.resources, created] } : t)) } : m));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const undoTopic = async (topicId: number) => {
    try {
      await api(`/api/topics/${topicId}/undo`, { method: "POST" });
      load(); // undo can restore a deleted resource (new id) or revert a field -- simplest to just refetch
    } catch (e: any) {
      setError(e.message);
    }
  };

  const deleteTopic = async (topicId: number) => {
    try {
      await api(`/api/topics/${topicId}`, { method: "DELETE" });
      setModule((m) => (m ? { ...m, topics: m.topics.filter((t) => t.id !== topicId), topic_count: m.topic_count - 1 } : m));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const addTopic = async () => {
    if (!newTopicTitle.trim() || !module) return;
    try {
      const created = await api<TopicT>(`/api/modules/${slug}/topics`, {
        method: "POST",
        body: JSON.stringify({ title: newTopicTitle.trim() }),
      });
      setModule((m) => (m ? { ...m, topics: [...m.topics, created], topic_count: m.topic_count + 1 } : m));
      setNewTopicTitle("");
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="w-full max-w-none space-y-6">
      <div className="card p-5">
        <div className="flex items-center gap-1.5 mb-3 font-mono text-[11px]">
          <button onClick={() => navigate("/roadmap")} className="text-fog hover:text-snow">
            ← back to roadmap
          </button>
          {from && (
            <span className="text-fog">
              <span className="mx-1">›</span>
              {from}
            </span>
          )}
        </div>

        {error && <p className="text-danger text-sm">{error}</p>}
        {!module && !error && (
          <p className="text-fog text-sm font-mono animate-pulse">Athena is building your curriculum…</p>
        )}

        {module && (
          <>
            <h2 className="font-display text-xl font-semibold text-snow">
              <DecryptText text={module.title} />
            </h2>
            {module.summary && <p className="text-fog text-sm mt-1">{module.summary}</p>}
            <div className="flex gap-2 mt-3 flex-wrap font-mono text-[10px]">
              <span className="text-accent border border-accent/40 rounded px-1.5 py-0.5">
                {module.percent}% complete
              </span>
              <span className="text-fog border border-line rounded px-1.5 py-0.5">{module.topic_count} topics</span>
              <span className="text-fog border border-line rounded px-1.5 py-0.5">~{module.total_minutes} min</span>
            </div>
            <div className="flex gap-2 mt-3">
              <input
                className="input"
                placeholder="Add a topic to this module…"
                value={newTopicTitle}
                onChange={(e) => setNewTopicTitle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addTopic()}
              />
              <span className="font-mono text-[10px] text-fog self-center shrink-0">Enter to add</span>
            </div>
          </>
        )}
      </div>

      {module && (
        <div className="space-y-3">
          {module.topics.map((t) => (
            <TopicCard
              key={t.id}
              topic={t}
              onToggleDone={toggleTopic}
              onResourceSave={saveResource}
              onResourceDelete={deleteResource}
              onAddResource={addResource}
              onUpload={uploadFile}
              onUndo={undoTopic}
              onDeleteTopic={deleteTopic}
              onResourceError={setError}
            />
          ))}
        </div>
      )}

      {/* Comprehension cards, below the topics because they test what the
          topics taught. Rendered only for modules derived from a repo:
          `code_repo_id` is null on seed and generated modules, which have no
          import graph to ask questions about. */}
      {module && module.code_repo_id != null && (
        <div className="mt-4">
          <CardPractice repoId={module.code_repo_id} moduleId={module.id} />
        </div>
      )}
    </div>
  );
}
