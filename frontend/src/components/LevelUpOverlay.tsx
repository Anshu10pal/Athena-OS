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
      setTimeout(() => setLevel(null), 3000);
    };
    window.addEventListener("athena:levelup", handler);
    return () => window.removeEventListener("athena:levelup", handler);
  }, []);

  return (
    <AnimatePresence>
      {level !== null && (
        <motion.div
          className="fixed bottom-6 right-6 z-50 card px-4 py-3 flex items-center gap-3"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
        >
          <span className="w-2 h-2 rounded-full bg-accent" />
          <p className="text-sm text-snow">
            Level up — you're now <span className="text-accent font-semibold">Level {level}</span>
          </p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
