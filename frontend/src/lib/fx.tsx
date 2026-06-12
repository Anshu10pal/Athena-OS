import { useEffect, useRef, useState } from "react";

const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%&";

/** Heading text that scrambles through glyphs before resolving. */
export function DecryptText({ text, className = "", speed = 28 }: { text: string; className?: string; speed?: number }) {
  const [display, setDisplay] = useState("");
  useEffect(() => {
    let frame = 0;
    const t = setInterval(() => {
      frame++;
      const resolved = Math.floor(frame / 2);
      setDisplay(
        text
          .split("")
          .map((ch, i) => (i < resolved ? ch : ch === " " ? " " : GLYPHS[Math.floor(Math.random() * GLYPHS.length)]))
          .join("")
      );
      if (resolved >= text.length) clearInterval(t);
    }, speed);
    return () => clearInterval(t);
  }, [text, speed]);
  return <span className={className}>{display || "\u00A0"}</span>;
}

/** Number that counts up with a digit shuffle. */
export function AnimatedNumber({ value, duration = 700, className = "" }: { value: number; duration?: number; className?: string }) {
  const [display, setDisplay] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    const start = performance.now();
    let raf = 0;
    const loop = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(Math.round(from + (value - from) * eased));
      if (p < 1) raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <span className={className}>{display}</span>;
}
