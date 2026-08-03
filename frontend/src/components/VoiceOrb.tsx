import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { useOrb } from "../store/orb";

export type { OrbState } from "../store/orb";
import type { OrbState } from "../store/orb";

const ringConfig: Record<OrbState, { speed: number; scale: number[]; opacity: number }> = {
  idle: { speed: 3.2, scale: [1, 1.03, 1], opacity: 0.25 },
  listening: { speed: 1.6, scale: [1, 1.08, 1], opacity: 0.5 },
  thinking: { speed: 0.9, scale: [1, 1.05, 1], opacity: 0.4 },
  speaking: { speed: 1.1, scale: [1, 1.12, 1], opacity: 0.6 },
};

/** A simple pulsing state indicator, audio-reactive when mic/TTS is live. */
export default function VoiceOrb({ state, size = 120 }: { state: OrbState; size?: number }) {
  const cfg = ringConfig[state];
  const { audioLevel } = useOrb();
  const reactiveRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const l = audioLevel.current;
      if (reactiveRef.current) {
        reactiveRef.current.style.transform = `scale(${1 + l * 0.3})`;
      }
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [audioLevel]);

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <motion.div
        className="absolute rounded-full border border-accent"
        style={{ width: size * 0.6, height: size * 0.6 }}
        animate={{ scale: cfg.scale, opacity: [cfg.opacity * 0.4, cfg.opacity, cfg.opacity * 0.4] }}
        transition={{ duration: cfg.speed, repeat: Infinity, ease: "easeInOut" }}
      />
      <div ref={reactiveRef} style={{ transition: "transform 0.08s linear" }}>
        <div className="rounded-full bg-accent" style={{ width: size * 0.28, height: size * 0.28 }} />
      </div>
      <span className="sr-only">Athena is {state}</span>
    </div>
  );
}
