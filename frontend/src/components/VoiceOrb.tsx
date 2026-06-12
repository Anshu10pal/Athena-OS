import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { useOrb } from "../store/orb";

export type { OrbState } from "../store/orb";
import type { OrbState } from "../store/orb";

const ringConfig: Record<OrbState, { speed: number; scale: number[]; opacity: number }> = {
  idle: { speed: 14, scale: [1, 1.02, 1], opacity: 0.35 },
  listening: { speed: 6, scale: [1, 1.08, 1], opacity: 0.7 },
  thinking: { speed: 2.4, scale: [1, 1.04, 1], opacity: 0.55 },
  speaking: { speed: 4, scale: [1, 1.12, 1], opacity: 0.85 },
};

/** The Athena orb — a breathing astrolabe, audio-reactive when mic/TTS is live. */
export default function VoiceOrb({ state, size = 120 }: { state: OrbState; size?: number }) {
  const cfg = ringConfig[state];
  const { audioLevel } = useOrb();
  const reactiveRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const l = audioLevel.current;
      if (reactiveRef.current) {
        reactiveRef.current.style.transform = `scale(${1 + l * 0.45})`;
        reactiveRef.current.style.filter = l > 0.05 ? `drop-shadow(0 0 ${6 + l * 18}px rgba(212,179,106,0.5))` : "none";
      }
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [audioLevel]);

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <motion.div
        className="absolute inset-0 rounded-full"
        style={{ boxShadow: "0 0 60px 8px rgba(212,179,106,0.18)" }}
        animate={{ opacity: [cfg.opacity * 0.5, cfg.opacity, cfg.opacity * 0.5] }}
        transition={{ duration: cfg.speed / 2, repeat: Infinity, ease: "easeInOut" }}
      />
      {[0.95, 0.75, 0.55].map((r, i) => (
        <motion.svg
          key={i}
          viewBox="0 0 100 100"
          className="absolute"
          style={{ width: size * r, height: size * r }}
          animate={{ rotate: i % 2 === 0 ? 360 : -360 }}
          transition={{ duration: cfg.speed * (i + 1.5), repeat: Infinity, ease: "linear" }}
        >
          <circle
            cx="50"
            cy="50"
            r="48"
            fill="none"
            stroke="#D4B36A"
            strokeOpacity={cfg.opacity - i * 0.12}
            strokeWidth={i === 0 ? 0.8 : 1.4}
            strokeDasharray={i === 0 ? "2 6" : i === 1 ? "30 14" : "10 22"}
            strokeLinecap="round"
          />
        </motion.svg>
      ))}
      <div ref={reactiveRef} style={{ transition: "transform 0.08s linear" }}>
        <motion.div
          className="rounded-full bg-gradient-to-br from-brass to-brassdim"
          style={{ width: size * 0.32, height: size * 0.32 }}
          animate={{ scale: cfg.scale }}
          transition={{ duration: state === "thinking" ? 0.9 : 2.4, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>
      <span className="sr-only">Athena is {state}</span>
    </div>
  );
}
