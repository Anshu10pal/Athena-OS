import { useEffect, useState } from "react";
import { useOrb } from "../store/orb";

function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function useSessionTimer() {
  const [session] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - session) / 1000)), 1000);
    return () => clearInterval(t);
  }, [session]);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/**
 * GEMINI/GROQ dots render neutral grey rather than a hardcoded "online" green —
 * there is no real availability/health check for either provider in the backend
 * yet (only a generic "no provider available" error raised inside an actual
 * completion call). Wire these up to a real status source if one gets added.
 */
export default function HudStrip({ variant = "full" }: { variant?: "full" | "compact" }) {
  const { state } = useOrb();
  const now = useClock();
  const session = useSessionTimer();
  const clock = `${String(now.getUTCHours()).padStart(2, "0")}:${String(now.getUTCMinutes()).padStart(2, "0")}:${String(now.getUTCSeconds()).padStart(2, "0")} UTC`;

  if (variant === "compact") {
    return (
      <span className="pill">
        STATE <span style={{ color: "var(--fg)" }}>{state.toUpperCase()}</span>
      </span>
    );
  }

  return (
    <div className="hud">
      <span>{clock}</span>
      <span>SESSION <b>{session}</b></span>
      <span>GEMINI<i className="dot grey" /></span>
      <span>GROQ<i className="dot grey" /></span>
      <span className="sep">STATE <b>{state.toUpperCase()}</b></span>
    </div>
  );
}
