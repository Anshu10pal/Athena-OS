import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import GeoCore from "../components/GeoCore";
import { api } from "../lib/api";
import { useWakeWord } from "../lib/useWakeWord";
import { useAuth } from "../store/auth";

interface Dash {
  roadmap_progress: number;
  roadmap_title: string | null;
  reviews_due: number;
  memory_strength: number;
}

export default function Hub() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const mouse = useRef({ x: 0, y: 0 });
  const [dash, setDash] = useState<Dash | null>(null);
  const [briefing, setBriefing] = useState("");
  const [wakeReady, setWakeReady] = useState(false);
  const [wakeHint, setWakeHint] = useState("");

  useWakeWord(() => navigate("/chat"), (r) => setWakeReady(r));

  useEffect(() => {
    if (localStorage.getItem("athena_wakeword") !== "1") return;
    const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SR) { setWakeHint("Wake word needs Chrome or Edge"); return; }
    const t = setTimeout(() => {
      setWakeReady((ready) => {
        if (!ready) setWakeHint("Allow the microphone, then reload to enable “Hey Athena”");
        return ready;
      });
    }, 3500);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    api<Dash>("/api/analytics/dashboard").then(setDash).catch(() => {});
    const today = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem("athena_briefing_date") !== today) {
      api<{ text: string }>("/api/briefing").then((r) => {
        localStorage.setItem("athena_briefing_date", today);
        let i = 0;
        const t = setInterval(() => { i += 2; setBriefing(r.text.slice(0, i)); if (i >= r.text.length) clearInterval(t); }, 20);
      }).catch(() => {});
    }
  }, []);

  const onMove = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    mouse.current = { x: (e.clientX - r.left) / r.width - 0.5, y: (e.clientY - r.top) / r.height - 0.5 };
  };

  const reviewsDue = dash?.reviews_due ?? 0;

  return (
    <div onMouseMove={onMove} style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <GeoCore mouse={mouse} />

      {/* clickable core hit-area (core is WebGL, give it a real target) */}
      <button
        onClick={() => navigate("/chat")}
        title="Talk to Athena"
        aria-label="Talk to Athena"
        style={{ position: "absolute", left: "50%", top: "46%", transform: "translate(-50%,-50%)", width: 150, height: 150, borderRadius: "50%", background: "transparent", border: "none", cursor: "pointer", zIndex: 13 }}
      />

      {/* welcome + briefing, below the core */}
      <div style={{ position: "absolute", left: "50%", bottom: "12%", transform: "translateX(-50%)", zIndex: 10, width: 460, textAlign: "center", pointerEvents: "none" }}>
        <p style={{ margin: 0, fontSize: 24, fontWeight: 500, color: "#fff", letterSpacing: 0.5, textShadow: "0 0 24px rgba(95,211,224,0.4)" }}>
          Welcome back, {user?.name?.split(" ")[0] ?? "Commander"}
        </p>
        <p style={{ margin: "10px auto 0", fontFamily: "monospace", fontSize: 11.5, color: "#9AA4B4", maxWidth: 380, lineHeight: 1.6, minHeight: 30 }}>
          {briefing || "click the core to talk \u00b7 navigate from the left \u00b7 Ctrl+K anywhere"}
          {briefing && <span style={{ display: "inline-block", width: 6, height: 12, background: "#5FD3E0", marginLeft: 2, verticalAlign: "middle" }} className="animate-pulse" />}
        </p>
        {reviewsDue > 0 && (
          <button onClick={() => navigate("/review")} style={{ pointerEvents: "auto", marginTop: 14, background: "rgba(95,211,224,0.1)", border: "1px solid rgba(95,211,224,0.4)", color: "#7FE9F0", borderRadius: 10, padding: "7px 16px", fontFamily: "monospace", fontSize: 11, cursor: "pointer" }}>
            {reviewsDue} review{reviewsDue > 1 ? "s" : ""} due \u2192
          </button>
        )}
        {wakeReady ? (
          <p style={{ margin: "12px 0 0", fontFamily: "monospace", fontSize: 9.5, letterSpacing: 1.5, color: "#5FD3E0" }}>
            {"\u25CF"} LISTENING FOR {"\u201C"}HEY ATHENA{"\u201D"}
          </p>
        ) : wakeHint ? (
          <p style={{ margin: "12px 0 0", fontFamily: "monospace", fontSize: 9.5, letterSpacing: 1, color: "#D98A6A" }}>
            {wakeHint}
          </p>
        ) : null}
      </div>
    </div>
  );
}
