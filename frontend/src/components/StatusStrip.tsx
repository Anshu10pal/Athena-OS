import { useEffect, useState } from "react";

export default function StatusStrip() {
  const [now, setNow] = useState(new Date());
  const [session] = useState(() => Date.now());
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => {
      setNow(new Date());
      tick((x) => x + 1);
    }, 1000);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.floor((Date.now() - session) / 1000);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  return (
    <div className="flex items-center gap-4 font-mono text-[10px] text-fog">
      <span>{now.toUTCString().slice(17, 25)} UTC</span>
      <span>SESSION {mm}:{ss}</span>
      <span>
        GEMINI <span className="text-sage">●</span>
      </span>
      <span>
        GROQ <span className="text-sage">●</span>
      </span>
    </div>
  );
}
