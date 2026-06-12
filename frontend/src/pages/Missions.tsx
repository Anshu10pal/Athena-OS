import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { DecryptText } from "../lib/fx";
import { chime } from "../lib/sound";
import { useAuth } from "../store/auth";
import { useOrb } from "../store/orb";

interface Mission {
  id: number;
  objective: string;
  difficulty: string;
  xp_reward: number;
  skills_gained: string[];
  status: string;
  isNew?: boolean;
}

const DIFF_COLOR: Record<string, string> = { easy: "text-sage", medium: "text-brass", hard: "text-ember" };

export default function Missions() {
  const { refresh } = useAuth();
  const { notifyXp } = useOrb();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<Mission[]>("/api/missions/today")
      .then(setMissions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const complete = async (id: number) => {
    const res = await api<{ xp: number; xp_gained: number; new_mission: Mission | null }>(`/api/missions/${id}/complete`, { method: "POST" });
    chime();
    notifyXp(res.xp, res.xp_gained);
    setMissions((ms) => {
      const updated = ms.map((m) => (m.id === id ? { ...m, status: "completed" } : m));
      return res.new_mission ? [...updated, { ...res.new_mission, isNew: true }] : updated;
    });
    refresh();
  };

  const active = missions.filter((m) => m.status !== "completed");
  const done = missions.filter((m) => m.status === "completed");

  return (
    <div className="w-full max-w-none space-y-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-snow">
          <DecryptText text="Daily directives" />
        </h2>
        <p className="text-fog text-sm mt-1 font-mono">complete one — a new directive deploys in its place</p>
      </div>

      {loading && <p className="text-fog text-sm font-mono animate-pulse">Athena is preparing your directives…</p>}
      {!loading && missions.length === 0 && (
        <div className="card p-5">
          <p className="text-fog text-sm">No directives yet — generate a roadmap first, then return.</p>
        </div>
      )}

      <AnimatePresence>
        {active.map((m) => (
          <motion.div
            key={m.id}
            layout
            initial={m.isNew ? { opacity: 0, x: 40 } : false}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -40 }}
            className="card p-4 flex items-center justify-between gap-4"
          >
            <div className="min-w-0">
              {m.isNew && <p className="font-mono text-[9px] tracking-[0.3em] text-brass mb-1">NEW DIRECTIVE</p>}
              <p className="text-sm text-snow">{m.objective}</p>
              <p className="font-mono text-[10px] text-fog mt-1.5">
                <span className={DIFF_COLOR[m.difficulty] ?? "text-fog"}>{m.difficulty}</span> · +{m.xp_reward} XP
                {m.skills_gained?.length > 0 && <> · {m.skills_gained.join(", ")}</>}
              </p>
            </div>
            <button className="btn-brass text-sm shrink-0" onClick={() => complete(m.id)}>
              Complete
            </button>
          </motion.div>
        ))}
      </AnimatePresence>

      {done.length > 0 && (
        <div className="space-y-2">
          <p className="font-mono text-[10px] tracking-widest text-fog">COMPLETED TODAY</p>
          {done.map((m) => (
            <div key={m.id} className="px-4 py-2.5 border border-line rounded-lg text-sm text-fog line-through opacity-60">
              {m.objective}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
