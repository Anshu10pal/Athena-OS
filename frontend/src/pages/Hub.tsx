import { motion } from "framer-motion";
import { Database, Mic2, Presentation, Route, Speech, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ArcGauge from "../components/ArcGauge";
import ParticleField from "../components/ParticleField";
import StatusStrip from "../components/StatusStrip";
import VoiceOrb from "../components/VoiceOrb";
import { api } from "../lib/api";
import { DecryptText } from "../lib/fx";
import { useAuth } from "../store/auth";

interface Dash {
  level: number;
  streak: number;
  roadmap_progress: number;
  roadmap_title: string | null;
  interview_readiness: number;
  presentations_analyzed: number;
  oratory_filler_rate: number | null;
  speeches: number;
  vault_entries: number;
  digital_twin: Record<string, number>;
}

export default function Hub() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [dash, setDash] = useState<Dash | null>(null);
  const [openMissions, setOpenMissions] = useState<number | null>(null);
  const [briefing, setBriefing] = useState("");

  useEffect(() => {
    api<Dash>("/api/analytics/dashboard").then(setDash).catch(() => {});
    api<any[]>("/api/missions/today")
      .then((ms) => setOpenMissions(ms.filter((m) => m.status !== "completed").length))
      .catch(() => {});
    const today = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem("athena_briefing_date") !== today) {
      api<{ text: string }>("/api/briefing")
        .then((r) => {
          localStorage.setItem("athena_briefing_date", today);
          let i = 0;
          const t = setInterval(() => {
            i += 2;
            setBriefing(r.text.slice(0, i));
            if (i >= r.text.length) clearInterval(t);
          }, 18);
        })
        .catch(() => {});
    }
  }, []);

  // Stations on a true orbital ring around the orb (degrees, 0 = right, CCW)
  const stations = [
    { name: "Roadmap", icon: Route, stat: dash ? `${dash.roadmap_progress}% · ${dash.roadmap_title ?? "none yet"}` : "…", to: "/roadmap", angle: -125 },
    { name: "Missions", icon: Target, stat: openMissions === null ? "…" : `${openMissions} open directives`, to: "/missions", angle: -55 },
    { name: "Interview arena", icon: Mic2, stat: dash ? `readiness ${dash.interview_readiness}` : "…", to: "/interview", angle: 180 },
    { name: "Oratory deck", icon: Speech, stat: dash?.oratory_filler_rate != null ? `${dash.oratory_filler_rate} fillers/min` : "no sessions yet", to: "/oratory", angle: 0 },
    { name: "Presentation", icon: Presentation, stat: dash ? `${dash.presentations_analyzed} decks analyzed` : "…", to: "/presentation", angle: 125 },
    { name: "Knowledge vault", icon: Database, stat: dash ? `${dash.vault_entries} entries` : "…", to: "/vault", angle: 55 },
  ];

  return (
    <div className="min-h-screen relative overflow-hidden">
      <ParticleField />
      <div className="absolute top-4 left-5 font-mono text-[10px] tracking-widest text-fog" style={{ zIndex: 10 }}>
        ATHENA OS · COMMAND HUB
      </div>
      <div className="absolute top-4 right-5 flex items-center gap-4" style={{ zIndex: 10 }}>
        <StatusStrip />
        <button onClick={logout} className="font-mono text-[10px] text-fog hover:text-ember">
          SIGN OUT
        </button>
      </div>

      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center max-w-md text-center" style={{ zIndex: 10 }}>
        <button onClick={() => navigate("/chat")} title="Talk to Athena" className="cursor-pointer">
          <VoiceOrb state="idle" size={170} />
        </button>
        <h1 className="font-display text-xl mt-4 text-snow">
          <DecryptText text={`Welcome back, ${user?.name?.split(" ")[0] ?? "Commander"}`} />
        </h1>
        <p className="text-fog text-xs font-mono mt-2 min-h-10 leading-relaxed">
          {briefing || `Day ${user?.streak ?? 0} streak · click the orb to talk · Ctrl+K to command`}
          {briefing && <span className="inline-block w-1.5 h-3 bg-brass ml-0.5 animate-pulse align-middle" />}
        </p>
        {dash && (
          <div className="flex gap-3 mt-4">
            {Object.entries(dash.digital_twin)
              .slice(0, 5)
              .map(([k, v]) => (
                <ArcGauge key={k} value={v} label={k.replace(/_/g, " ").slice(0, 12)} size={64} />
              ))}
          </div>
        )}
      </div>

      {stations.map((s, i) => {
        const rad = (s.angle * Math.PI) / 180;
        const x = Math.cos(rad);
        const y = Math.sin(rad);
        return (
        <motion.button
          key={s.to}
          onClick={() => navigate(s.to)}
          initial={{ opacity: 0, scale: 0.7 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.25 + i * 0.12 }}
          whileHover={{ scale: 1.06 }}
          className="card w-44 px-4 py-3 text-left hover:border-brass/50 transition-colors"
          style={{
            zIndex: 10,
            position: "absolute",
            left: `calc(50% + ${x.toFixed(3)} * min(36vw, 460px))`,
            top: `calc(50% + ${y.toFixed(3)} * min(36vh, 300px))`,
            transform: "translate(-50%, -50%)",
          }}
        >
          <div className="flex items-center gap-2">
            <s.icon size={16} className="text-brass" />
            <span className="font-display text-sm text-snow">{s.name}</span>
          </div>
          <p className="font-mono text-[10px] text-fog mt-1.5 truncate">{s.stat}</p>
        </motion.button>
        );
      })}
    </div>
  );
}
