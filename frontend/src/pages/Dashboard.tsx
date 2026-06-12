import { useEffect, useRef, useState } from "react";
import VoiceOrb from "../components/VoiceOrb";
import { api } from "../lib/api";
import { chime } from "../lib/sound";
import { useAuth } from "../store/auth";
import { useOrb } from "../store/orb";

interface Mission {
  id: number;
  objective: string;
  difficulty: string;
  xp_reward: number;
  status: string;
}

interface Dash {
  xp: number;
  level: number;
  streak: number;
  roadmap_progress: number;
  roadmap_title: string | null;
  interview_readiness: number;
  presentations_analyzed: number;
  missions_completed: number;
  skills: Record<string, number>;
  digital_twin: Record<string, number>;
}

export default function Dashboard() {
  const { user, refresh } = useAuth();
  const { notifyXp } = useOrb();
  const [dash, setDash] = useState<Dash | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [missionsLoading, setMissionsLoading] = useState(true);
  const [briefing, setBriefing] = useState("");
  const briefingFull = useRef("");

  const load = () => {
    api<Dash>("/api/analytics/dashboard").then(setDash).catch(() => {});
    api<Mission[]>("/api/missions/today")
      .then(setMissions)
      .catch(() => {})
      .finally(() => setMissionsLoading(false));
  };

  useEffect(() => {
    load();
    const today = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem("athena_briefing_date") !== today) {
      api<{ text: string }>("/api/briefing")
        .then((r) => {
          localStorage.setItem("athena_briefing_date", today);
          briefingFull.current = r.text;
          let i = 0;
          const t = setInterval(() => {
            i += 2;
            setBriefing(briefingFull.current.slice(0, i));
            if (i >= briefingFull.current.length) clearInterval(t);
          }, 18);
        })
        .catch(() => {});
    }
  }, []);

  const completeMission = async (id: number) => {
    const res = await api<{ xp: number; xp_gained: number }>(`/api/missions/${id}/complete`, { method: "POST" });
    if (res.xp_gained > 0) {
      chime();
      notifyXp(res.xp, res.xp_gained);
    }
    await refresh();
    load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="card p-5 flex items-center gap-5">
        <VoiceOrb state={briefing && briefing !== briefingFull.current ? "speaking" : "idle"} size={72} />
        <div className="min-w-0">
          <h2 className="font-display text-xl font-semibold">Welcome back, {user?.name?.split(" ")[0]}</h2>
          <p className="text-fog text-sm mt-1 leading-relaxed">
            {briefing ||
              (user?.target_role
                ? `Target: ${user.target_role}`
                : "Set a target role in your roadmap to unlock personalized missions.")}
            {briefing && briefing !== briefingFull.current && (
              <span className="inline-block w-1.5 h-3 bg-brass ml-0.5 animate-pulse align-middle" />
            )}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Level" value={dash ? `${dash.level}` : "—"} />
        <Stat label="Roadmap" value={dash ? `${dash.roadmap_progress}%` : "—"} sub={dash?.roadmap_title ?? ""} />
        <Stat label="Interview readiness" value={dash ? `${dash.interview_readiness}` : "—"} sub="out of 100" />
        <Stat label="Missions done" value={dash ? `${dash.missions_completed}` : "—"} />
      </div>

      <section className="card p-5">
        <h3 className="font-display font-medium mb-3">Today's missions</h3>
        {missionsLoading ? (
          <p className="text-fog text-sm">Athena is preparing your missions…</p>
        ) : missions.length === 0 ? (
          <p className="text-fog text-sm">No missions yet — generate a roadmap first, then check back.</p>
        ) : (
          <ul className="space-y-2">
            {missions.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 bg-panel2 border border-line rounded-lg px-4 py-3">
                <div>
                  <p className={m.status === "completed" ? "line-through text-fog" : ""}>{m.objective}</p>
                  <p className="text-xs text-fog mt-0.5 font-mono">
                    {m.difficulty} · +{m.xp_reward} XP
                  </p>
                </div>
                {m.status !== "completed" && (
                  <button className="btn-brass text-sm shrink-0" onClick={() => completeMission(m.id)}>
                    Complete
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card p-5">
        <h3 className="font-display font-medium mb-3">Digital twin</h3>
        <div className="space-y-2">
          {dash &&
            Object.entries(dash.digital_twin).map(([k, v]) => (
              <div key={k} className="flex items-center gap-3 text-sm">
                <span className="w-44 text-fog capitalize">{k.replace(/_/g, " ")}</span>
                <div className="flex-1 h-1.5 bg-panel2 rounded-full overflow-hidden">
                  <div className="h-full bg-brass rounded-full transition-all" style={{ width: `${v}%` }} />
                </div>
                <span className="font-mono text-xs w-8 text-right">{v}</span>
              </div>
            ))}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-4">
      <p className="text-fog text-xs uppercase tracking-wider">{label}</p>
      <p className="font-display text-2xl mt-1">{value}</p>
      {sub && <p className="text-fog text-xs mt-0.5 truncate">{sub}</p>}
    </div>
  );
}
