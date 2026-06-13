import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import HoloScene from "../components/HoloScene";
import StatusStrip from "../components/StatusStrip";
import { api } from "../lib/api";
import { useWakeWord } from "../lib/useWakeWord";
import { useAuth } from "../store/auth";

interface Dash {
  level: number;
  streak: number;
  roadmap_progress: number;
  roadmap_title: string | null;
  interview_readiness: number;
  oratory_filler_rate: number | null;
  vault_entries: number;
  reviews_due: number;
  memory_strength: number;
  achievements_unlocked: number;
}

// Flanking layout — center column reserved for core + text (no overlap).
const STATIONS = [
  { name: "Roadmap", icon: "🗺", to: "/roadmap", x: -310, y: -160, z: 70, key: "roadmap" },
  { name: "Missions", icon: "◎", to: "/missions", x: 310, y: -160, z: 110, key: "missions" },
  { name: "Interview", icon: "◈", to: "/interview", x: -355, y: -10, z: 120, key: "interview" },
  { name: "Oratory", icon: "∿", to: "/oratory", x: 355, y: -10, z: 90, key: "oratory" },
  { name: "Vault", icon: "⬡", to: "/vault", x: -315, y: 150, z: 45, key: "vault" },
  { name: "Review", icon: "↻", to: "/review", x: 315, y: 150, z: 120, key: "review" },
];

export default function Hub() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const mouse = useRef({ x: 0, y: 0 });
  const sceneRef = useRef<HTMLDivElement>(null);
  const [dash, setDash] = useState<Dash | null>(null);
  const [openMissions, setOpenMissions] = useState<number | null>(null);
  const [briefing, setBriefing] = useState("");
  const [mounted, setMounted] = useState(false);
  const [wakeReady, setWakeReady] = useState(false);

  useWakeWord(
    () => navigate("/chat"),
    () => setWakeReady(true)
  );

  useEffect(() => {
    setTimeout(() => setMounted(true), 100);
    api<Dash>("/api/analytics/dashboard").then(setDash).catch(() => {});
    api<any[]>("/api/missions/today").then((ms) => setOpenMissions(ms.filter((m) => m.status !== "completed").length)).catch(() => {});
    const today = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem("athena_briefing_date") !== today) {
      api<{ text: string }>("/api/briefing").then((r) => {
        localStorage.setItem("athena_briefing_date", today);
        let i = 0;
        const t = setInterval(() => { i += 2; setBriefing(r.text.slice(0, i)); if (i >= r.text.length) clearInterval(t); }, 20);
      }).catch(() => {});
    }
  }, []);

  const statOf = (key: string): string => {
    if (!dash) return "…";
    switch (key) {
      case "roadmap": return `${dash.roadmap_progress}% · ${dash.roadmap_title ?? "none yet"}`;
      case "missions": return openMissions === null ? "…" : `${openMissions} open directives`;
      case "interview": return `readiness ${dash.interview_readiness}`;
      case "oratory": return dash.oratory_filler_rate != null ? `${dash.oratory_filler_rate} fillers/min` : "no sessions yet";
      case "vault": return `${dash.vault_entries} entries`;
      case "review": return dash.reviews_due > 0 ? `${dash.reviews_due} due today` : "all reviewed";
      default: return "";
    }
  };

  const onMove = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    mouse.current = { x: (e.clientX - r.left) / r.width - 0.5, y: (e.clientY - r.top) / r.height - 0.5 };
    const scene = sceneRef.current;
    if (scene) scene.style.transform = `rotateY(${mouse.current.x * 13}deg) rotateX(${-mouse.current.y * 11}deg)`;
    document.querySelectorAll<HTMLElement>(".holo-card").forEach((el) => {
      if (el.matches(":hover")) return;
      const bx = +el.dataset.bx!, by = +el.dataset.by!, z = +el.dataset.z!, sc = +el.dataset.sc!;
      el.style.transform = `translate(calc(-50% + ${bx - mouse.current.x * 26}px), calc(-50% + ${by - mouse.current.y * 26}px)) translateZ(${z}px) scale(${sc})`;
    });
  };
  const onLeave = () => {
    mouse.current = { x: 0, y: 0 };
    if (sceneRef.current) sceneRef.current.style.transform = "";
  };

  return (
    <div
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      style={{
        position: "fixed", inset: 0, overflow: "hidden", cursor: "crosshair",
        background: "radial-gradient(ellipse at 50% 35%, #0E141E 0%, #080B11 50%, #04060A 100%)",
        perspective: "900px",
      }}
    >
      <div ref={sceneRef} style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d", transition: "transform .15s ease-out" }}>
        <HoloScene mouse={mouse} />

        {/* receding floor grid */}
        <div style={{
          position: "absolute", left: "-50%", right: "-50%", bottom: -80, height: 340,
          backgroundImage: "linear-gradient(rgba(95,211,224,0.12) 1px,transparent 1px),linear-gradient(90deg,rgba(95,211,224,0.10) 1px,transparent 1px)",
          backgroundSize: "48px 48px", transform: "rotateX(74deg) translateZ(-120px)", transformOrigin: "bottom",
          WebkitMaskImage: "linear-gradient(to top,#000 0%,transparent 80%)", maskImage: "linear-gradient(to top,#000 0%,transparent 80%)",
          zIndex: 2,
        }} />

        {/* clickable orb hit-area — sits over the WebGL core (which is lifted up) */}
        <button
          onClick={() => navigate("/chat")}
          title="Talk to Athena"
          aria-label="Talk to Athena"
          style={{
            position: "absolute", left: "50%", top: "38%", transform: "translate(-50%,-50%)",
            width: 150, height: 150, borderRadius: "50%", background: "transparent",
            border: "none", cursor: "pointer", zIndex: 13,
          }}
        />

        {/* welcome + briefing — positioned BELOW the orb, clear of it */}
        <div style={{ position: "absolute", left: "50%", top: "62%", transform: "translateX(-50%)", zIndex: 10, width: 320, textAlign: "center", pointerEvents: "none" }}>
          <p style={{ margin: 0, fontSize: 22, fontWeight: 500, color: "#fff", letterSpacing: 0.5, textShadow: "0 0 24px rgba(95,211,224,0.4)", whiteSpace: "nowrap" }}>
            Welcome back, {user?.name?.split(" ")[0] ?? "Commander"}
          </p>
          <p style={{ margin: "10px 0 0", fontFamily: "monospace", fontSize: 11, color: "#9AA4B4", maxWidth: 300, marginInline: "auto", lineHeight: 1.6, minHeight: 30 }}>
            {briefing || "click the orb to talk \u00b7 press Ctrl+K to command"}
            {briefing && <span style={{ display: "inline-block", width: 6, height: 12, background: "#5FD3E0", marginLeft: 2, verticalAlign: "middle" }} className="animate-pulse" />}
          </p>
          {wakeReady && (
            <p style={{ margin: "8px 0 0", fontFamily: "monospace", fontSize: 9.5, letterSpacing: 1.5, color: "#5FD3E0" }}>
              {"\u25CF"} LISTENING FOR {"\u201C"}HEY ATHENA{"\u201D"}
            </p>
          )}
        </div>

        {/* flanking glass station cards */}
        {STATIONS.map((s, i) => {
          const sc = 0.82 + s.z / 320;
          return (
            <button
              key={s.to}
              className="holo-card"
              data-bx={s.x} data-by={s.y} data-z={s.z} data-sc={sc}
              onClick={() => navigate(s.to)}
              style={{
                position: "absolute", left: "50%", top: "40%", width: 150, padding: "13px 16px", borderRadius: 14,
                background: "rgba(16,23,33,0.5)", backdropFilter: "blur(17px)", WebkitBackdropFilter: "blur(17px)",
                border: "1px solid rgba(212,179,106,0.24)", zIndex: 12, textAlign: "left", cursor: "pointer",
                boxShadow: "0 10px 38px rgba(0,0,0,0.5)", color: "#fff", willChange: "transform",
                opacity: mounted ? 1 : 0,
                transform: mounted
                  ? `translate(calc(-50% + ${s.x}px), calc(-50% + ${s.y}px)) translateZ(${s.z}px) scale(${sc})`
                  : "translate(-50%,-50%) scale(0.6)",
                transition: `opacity .9s ${i * 0.12}s, transform .9s cubic-bezier(.2,.8,.2,1) ${i * 0.12}s, border-color .25s, box-shadow .25s`,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(127,233,240,0.7)"; e.currentTarget.style.boxShadow = "0 0 34px rgba(95,211,224,0.3)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "rgba(212,179,106,0.24)"; e.currentTarget.style.boxShadow = "0 10px 38px rgba(0,0,0,0.5)"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span style={{ fontSize: 17, color: "#5FD3E0", textShadow: "0 0 11px rgba(95,211,224,0.7)" }}>{s.icon}</span>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</span>
              </div>
              <p style={{ margin: "8px 0 0", fontFamily: "monospace", fontSize: 9.5, color: "#9AA4B4", letterSpacing: 0.5 }}>{statOf(s.key)}</p>
            </button>
          );
        })}
      </div>

      {/* top bars (outside 3D scene so they stay crisp) */}
      <div style={{ position: "absolute", top: 16, left: 20, right: 20, display: "flex", justifyContent: "space-between", alignItems: "center", zIndex: 30 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 14px", borderRadius: 10, background: "rgba(14,20,30,0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(212,179,106,0.2)" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#5FD3E0", boxShadow: "0 0 9px #5FD3E0" }} />
          <span style={{ fontFamily: "monospace", fontSize: 10, letterSpacing: 3, color: "#E6ECF4" }}>ATHENA OS · COMMAND HUB</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{ padding: "7px 14px", borderRadius: 10, background: "rgba(14,20,30,0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(212,179,106,0.2)" }}>
            <StatusStrip />
          </div>
          <button onClick={logout} style={{ fontFamily: "monospace", fontSize: 10, color: "#9AA4B4", background: "none", border: "none", cursor: "pointer" }}>SIGN OUT</button>
        </div>
      </div>

      <div style={{ position: "absolute", bottom: 14, left: 0, right: 0, textAlign: "center", zIndex: 30, pointerEvents: "none" }}>
        <span style={{ fontFamily: "monospace", fontSize: 9.5, letterSpacing: 2, color: "#5a6478" }}>MOVE CURSOR TO EXPLORE · CLICK A PANEL TO ENTER · ESC RETURNS HERE</span>
      </div>
    </div>
  );
}
