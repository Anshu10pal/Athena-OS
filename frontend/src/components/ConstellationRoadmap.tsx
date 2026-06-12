import { motion } from "framer-motion";

interface Node {
  id: string;
  title: string;
  description: string;
  skills: string[];
  status: "locked" | "available" | "in_progress" | "completed" | "skipped";
  depends_on: string[];
}

interface Props {
  nodes: Node[];
  onSelect: (node: Node) => void;
}

/** Roadmap as a constellation: stars on a winding path, dependencies as faint lines.
 * Completed paths glow brass; clicking an available/in-progress star advances it. */
export default function ConstellationRoadmap({ nodes, onSelect }: Props) {
  const W = 760;
  const H = Math.max(320, Math.ceil(nodes.length / 4) * 150 + 80);
  const pos = nodes.map((_, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    const x = 90 + col * 190 + (row % 2 === 1 ? 60 : 0);
    const y = 70 + row * 140 + Math.sin(i * 1.7) * 22;
    return { x, y };
  });
  const byId = Object.fromEntries(nodes.map((n, i) => [n.id, i]));



  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Roadmap constellation">
      {nodes.map((n) =>
        n.depends_on.map((dep) => {
          const a = pos[byId[dep]];
          const b = pos[byId[n.id]];
          if (!a || !b) return null;
          const done = ["completed", "skipped"].includes(nodes[byId[dep]].status) && n.status !== "locked";
          return (
            <motion.line
              key={`${dep}-${n.id}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={done ? "#D4B36A" : "#222938"}
              strokeWidth={done ? 1.2 : 1}
              strokeDasharray={done ? "0" : "3 5"}
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: done ? 0.8 : 0.5 }}
              transition={{ duration: 1, delay: byId[n.id] * 0.06 }}
            />
          );
        })
      )}
      {nodes.map((n, i) => {
        const { x, y } = pos[i];
        const completed = n.status === "completed" || n.status === "skipped";
        const active = n.status === "in_progress";
        const available = n.status === "available";
        const interactive = n.status !== "locked";
        return (
          <motion.g
            key={n.id}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.05 }}
            style={{ cursor: interactive ? "pointer" : "default" }}
            onClick={() => interactive && onSelect(n)}
          >
            {(completed || active) && (
              <circle cx={x} cy={y} r={16} fill="none" stroke="#D4B36A" strokeOpacity={0.25} strokeWidth={1}>
                <animate attributeName="r" values="14;20;14" dur={active ? "1.6s" : "3.5s"} repeatCount="indefinite" />
                <animate attributeName="stroke-opacity" values="0.35;0.08;0.35" dur={active ? "1.6s" : "3.5s"} repeatCount="indefinite" />
              </circle>
            )}
            <circle
              cx={x}
              cy={y}
              r={7}
              fill={completed ? "#D4B36A" : active ? "rgba(212,179,106,0.25)" : "#11151D"}
              stroke={completed || active || available ? "#D4B36A" : "#222938"}
              strokeWidth={1.5}
              strokeOpacity={available || active || completed ? 0.9 : 0.7}
            />
            <text x={x} y={y + 24} textAnchor="middle" fontSize={10} fill={interactive || completed ? "#E8EBF1" : "#8A93A6"} fontFamily="Inter, sans-serif">
              {n.title.length > 24 ? n.title.slice(0, 23) + "…" : n.title}
            </text>
            <text x={x} y={y + 37} textAnchor="middle" fontSize={8.5} fill="#8A93A6" fontFamily="JetBrains Mono, monospace">
              {n.status === "skipped" ? "skipped" : completed ? "completed · review" : active ? "open dossier · assessment gate" : available ? "open dossier" : "locked"}
            </text>
          </motion.g>
        );
      })}
    </svg>
  );
}
