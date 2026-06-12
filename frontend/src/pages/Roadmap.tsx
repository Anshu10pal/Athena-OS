import { motion } from "framer-motion";
import { CheckCircle2, Circle, List, Lock, PlayCircle, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import ConstellationRoadmap from "../components/ConstellationRoadmap";
import NodeDossier from "../components/NodeDossier";
import { api } from "../lib/api";
import { DecryptText } from "../lib/fx";
import { unlock } from "../lib/sound";
import { useAuth } from "../store/auth";
import { useOrb } from "../store/orb";

interface Node {
  id: string;
  title: string;
  description: string;
  skills: string[];
  status: "locked" | "available" | "in_progress" | "completed" | "skipped";
  depends_on: string[];
  custom?: boolean;
}

interface RoadmapT {
  id: number;
  title: string;
  target_role: string;
  nodes: Node[];
  parent_roadmap_id: number | null;
  parent_node_id: string | null;
}

const icons: Record<string, JSX.Element> = {
  locked: <Lock size={18} className="text-fog" />,
  available: <Circle size={18} className="text-brass" />,
  in_progress: <PlayCircle size={18} className="text-sage" />,
  completed: <CheckCircle2 size={18} className="text-sage" />,
  skipped: <CheckCircle2 size={18} className="text-fog" />,
};

export default function Roadmap() {
  const { refresh } = useAuth();
  const { notifyXp } = useOrb();
  const [maps, setMaps] = useState<RoadmapT[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<"constellation" | "list">("constellation");
  const [selected, setSelected] = useState<Node | null>(null);
  const [newTopic, setNewTopic] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () => api<RoadmapT[]>("/api/roadmap").then(setMaps).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const roots = maps.filter((m) => !m.parent_roadmap_id);
  const current = maps.find((m) => m.id === currentId) ?? roots[0];

  // Breadcrumbs: walk parent chain up to the root
  const crumbs: RoadmapT[] = [];
  let walker: RoadmapT | undefined = current;
  while (walker) {
    crumbs.unshift(walker);
    const pid: number | null = walker.parent_roadmap_id;
    walker = pid ? maps.find((m) => m.id === pid) : undefined;
  }

  const generate = async () => {
    if (!role.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/roadmap/generate", { method: "POST", body: JSON.stringify({ target_role: role }) });
      setRole("");
      setCurrentId(null);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (mapId: number, nodeId: string, status: string) => {
    const res = await api<{ nodes: Node[]; xp: number; xp_gained: number }>(`/api/roadmap/${mapId}/node`, {
      method: "PATCH",
      body: JSON.stringify({ node_id: nodeId, status }),
    });
    if (res.xp_gained > 0) {
      unlock();
      notifyXp(res.xp, res.xp_gained);
    }
    setMaps((ms) => ms.map((m) => (m.id === mapId ? { ...m, nodes: res.nodes } : m)));
    refresh();
  };

  const openNode = (node: Node) => {
    if (node.status === "locked" || !current) return;
    if (node.status === "available") setStatus(current.id, node.id, "in_progress");
    setSelected(node);
  };

  const onAssessmentDone = (nodes: Node[] | null) => {
    if (nodes && current) {
      setMaps((ms) => ms.map((m) => (m.id === current.id ? { ...m, nodes } : m)));
      unlock();
      refresh();
      load(); // parent map may have auto-completed
      setSelected(null);
    }
  };

  const addTopic = async () => {
    if (!newTopic.trim() || !current || adding) return;
    setAdding(true);
    try {
      const r = await api<{ nodes: Node[] }>(`/api/roadmap/${current.id}/node`, {
        method: "POST",
        body: JSON.stringify({ title: newTopic.trim() }),
      });
      setMaps((ms) => ms.map((m) => (m.id === current.id ? { ...m, nodes: r.nodes } : m)));
      setNewTopic("");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="w-full max-w-none space-y-6">
      <div className="card p-5">
        <h2 className="font-display text-xl font-semibold">
          <DecryptText text="Roadmap engine" />
        </h2>
        <div className="flex gap-2 mt-3">
          <input
            className="input"
            placeholder="Target role, e.g. AI Architect"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && generate()}
          />
          <button className="btn-brass shrink-0" onClick={generate} disabled={busy}>
            {busy ? "Charting…" : "Generate"}
          </button>
        </div>
        {error && <p className="text-ember text-sm mt-2">{error}</p>}
        {roots.length > 1 && (
          <div className="flex gap-2 mt-3 flex-wrap">
            {roots.map((r) => (
              <button
                key={r.id}
                onClick={() => setCurrentId(r.id)}
                className={`font-mono text-[10px] border rounded px-2 py-1 transition-colors ${
                  current?.id === r.id ? "border-brass text-brass" : "border-line text-fog hover:text-snow"
                }`}
              >
                {r.title}
              </button>
            ))}
          </div>
        )}
      </div>

      {current && (
        <div className="card p-5">
          {crumbs.length > 1 && (
            <div className="flex items-center gap-1.5 mb-3 font-mono text-[11px] flex-wrap">
              {crumbs.map((c, i) => (
                <span key={c.id} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-fog">›</span>}
                  <button onClick={() => setCurrentId(c.id)} className={i === crumbs.length - 1 ? "text-brass" : "text-fog hover:text-snow"}>
                    {c.title.replace(" — deep dive", "")}
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between mb-1">
            <h3 className="font-display text-lg">{current.title}</h3>
            <button
              className="flex items-center gap-1.5 text-xs text-fog hover:text-brass border border-line rounded-md px-2 py-1"
              onClick={() => setView(view === "list" ? "constellation" : "list")}
            >
              {view === "list" ? <Sparkles size={13} /> : <List size={13} />}
              {view === "list" ? "Constellation" : "List"}
            </button>
          </div>
          <p className="text-fog text-sm mb-3">Target: {current.target_role}</p>
          <div className="flex gap-2 mb-5">
            <input
              className="input"
              placeholder="Add a topic to this map (e.g. Prompt Engineering)…"
              value={newTopic}
              onChange={(e) => setNewTopic(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addTopic()}
            />
            <span className="font-mono text-[10px] text-fog self-center shrink-0">{adding ? "adding…" : "Enter to add"}</span>
          </div>

          {view === "constellation" ? (
            <ConstellationRoadmap nodes={current.nodes} onSelect={(node) => openNode(node as Node)} />
          ) : (
            <div className="relative pl-7">
              <div className="absolute left-[8px] top-2 bottom-2 w-px bg-line" />
              {current.nodes.map((node, i) => (
                <motion.div
                  key={node.id}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="relative pb-5"
                >
                  <span className="absolute -left-7 top-1 bg-ink">{icons[node.status]}</span>
                  <div
                    className={`rounded-lg border px-4 py-3 ${
                      node.status === "completed" || node.status === "skipped"
                        ? "border-sage/40 bg-panel2"
                        : node.status === "locked"
                        ? "border-line opacity-50"
                        : "border-brass/40 bg-panel2"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-medium">
                        {node.title}
                        {node.custom && <span className="font-mono text-[8px] text-brass ml-2">CUSTOM</span>}
                      </p>
                      {node.status !== "locked" && (
                        <button className="text-xs text-brass hover:underline shrink-0" onClick={() => openNode(node)}>
                          {node.status === "completed" ? "Review dossier" : "Open dossier"}
                        </button>
                      )}
                    </div>
                    <p className="text-fog text-sm mt-1">{node.description}</p>
                    {node.skills?.length > 0 && <p className="text-xs font-mono text-fog mt-2">{node.skills.join(" · ")}</p>}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      )}

      {selected && current && (
        <NodeDossier
          roadmapId={current.id}
          node={current.nodes.find((n) => n.id === selected.id) ?? selected}
          onClose={() => setSelected(null)}
          onCompleted={(nodes) => onAssessmentDone(nodes)}
          onExpand={(submapId) => {
            setSelected(null);
            load();
            setCurrentId(submapId);
          }}
          onSkip={async () => {
            await setStatus(current.id, selected.id, "skipped");
            setSelected(null);
          }}
          onRemove={async () => {
            const r = await api<{ nodes: Node[] }>(`/api/roadmap/${current.id}/node/${selected.id}`, { method: "DELETE" });
            setMaps((ms) => ms.map((m) => (m.id === current.id ? { ...m, nodes: r.nodes } : m)));
            setSelected(null);
          }}
        />
      )}
    </div>
  );
}
