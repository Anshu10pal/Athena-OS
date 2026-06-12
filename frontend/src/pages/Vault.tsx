import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

interface Entry {
  id: number;
  kind: string;
  title: string;
  content: string;
  created_at: string;
}

interface Hit {
  text: string;
  score: number;
  kind: string;
}

export default function Vault() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const load = () => api<Entry[]>("/api/vault/entries").then(setEntries).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const search = async () => {
    if (!query.trim()) {
      setHits(null);
      return;
    }
    setHits(await api<Hit[]>(`/api/vault/search?q=${encodeURIComponent(query)}`));
  };

  const saveNote = async () => {
    if (!title.trim() || !content.trim()) return;
    await api("/api/vault/notes", { method: "POST", body: JSON.stringify({ title, content }) });
    setTitle("");
    setContent("");
    load();
  };

  return (
    <div className="w-full max-w-none space-y-6">
      <h2 className="font-display text-2xl font-semibold">Knowledge Vault</h2>

      <div className="flex gap-2">
        <input
          className="input"
          placeholder='Try: "What did I learn about LangGraph?"'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
        />
        <button className="btn-brass shrink-0" onClick={search}>
          <Search size={18} />
        </button>
      </div>

      {hits && (
        <div className="card p-5">
          <h3 className="font-display mb-3 text-sm text-fog">Semantic matches</h3>
          {hits.length === 0 ? (
            <p className="text-fog text-sm">Nothing in memory yet for that — go learn it, then it'll live here.</p>
          ) : (
            <ul className="space-y-3">
              {hits.map((h, i) => (
                <li key={i} className="text-sm border-l-2 border-brass pl-3">
                  <p className="whitespace-pre-wrap">{h.text}</p>
                  <p className="text-xs font-mono text-fog mt-1">
                    {h.kind} · relevance {h.score.toFixed(2)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="card p-5 space-y-2">
        <h3 className="font-display text-sm text-fog">Save a note</h3>
        <input className="input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="input min-h-24" placeholder="What did you learn?" value={content} onChange={(e) => setContent(e.target.value)} />
        <button className="btn-brass" onClick={saveNote}>
          Save to vault
        </button>
      </div>

      <div className="space-y-2">
        {entries.map((e) => (
          <div key={e.id} className="card px-4 py-3">
            <div className="flex items-center justify-between">
              <p className="font-medium text-sm">{e.title}</p>
              <span className="text-[10px] font-mono uppercase tracking-widest text-brass">{e.kind}</span>
            </div>
            <p className="text-fog text-sm mt-1 line-clamp-2">{e.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
