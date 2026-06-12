import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { levelUpSound } from "../lib/sound";

export default function LevelUpOverlay() {
  const [level, setLevel] = useState<number | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      setLevel(detail.level);
      levelUpSound();
      setTimeout(() => setLevel(null), 2200);
    };
    window.addEventListener("athena:levelup", handler);
    return () => window.removeEventListener("athena:levelup", handler);
  }, []);

  return (
    <AnimatePresence>
      {level !== null && (
        <motion.div
          className="fixed inset-0 z-50 flex flex-col items-center justify-center pointer-events-none"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          style={{ background: "rgba(11,14,20,0.75)" }}
        >
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="absolute rounded-full border border-brass"
              initial={{ width: 60, height: 60, opacity: 0.8 }}
              animate={{ width: 420 + i * 120, height: 420 + i * 120, opacity: 0 }}
              transition={{ duration: 1.6, delay: i * 0.15, ease: "easeOut" }}
            />
          ))}
          <motion.p
            className="font-mono text-xs tracking-[0.5em] text-brass"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
          >
            LEVEL UP
          </motion.p>
          <motion.h1
            className="font-display text-6xl font-bold text-snow mt-2"
            initial={{ scale: 0.7, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 200, damping: 14, delay: 0.25 }}
          >
            LEVEL <span className="text-brass">{level}</span>
          </motion.h1>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
