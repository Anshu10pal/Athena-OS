import { useEffect, useRef, useState } from "react";

/** Heading text. */
export function DecryptText({ text, className = "" }: { text: string; className?: string; speed?: number }) {
  return <span className={className}>{text}</span>;
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
