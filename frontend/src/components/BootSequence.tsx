import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

const BOOT_LINES = [
  "MEMORY CORE ............ ONLINE",
  "AGENT MESH (7) ......... ONLINE",
  "VECTOR STORE ........... ONLINE",
  "ROADMAP ENGINE ......... ONLINE",
  "VOICE SYSTEM ........... STANDBY",
];

export default function BootSequence({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [phase, setPhase] = useState<"typing" | "lines" | "out">("typing");
  const full = "ATHENA OS";

  useEffect(() => {
    let i = 0;
    const t = setInterval(() => {
      i++;
      setTitle(full.slice(0, i));
      if (i >= full.length) {
        clearInterval(t);
        setPhase("lines");
      }
    }, 90);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (phase !== "lines") return;
    let i = 0;
    const t = setInterval(() => {
      const line = BOOT_LINES[i];
      if (line !== undefined) setLines((prev) => [...prev, line]);
      i++;
      if (i >= BOOT_LINES.length) {
        clearInterval(t);
        setTimeout(() => setPhase("out"), 600);
      }
    }, 320);
    return () => clearInterval(t);
  }, [phase]);

  useEffect(() => {
    if (phase === "out") {
      const t = setTimeout(onDone, 700);
      return () => clearTimeout(t);
    }
  }, [phase, onDone]);

  return (
    <AnimatePresence>
      {phase !== "out" ? (
        <motion.div
          key="boot"
          className="fixed inset-0 z-50 bg-ink flex flex-col items-center justify-center cursor-pointer"
          onClick={onDone}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="rounded-full border border-brass/40"
            initial={{ width: 0, height: 0, opacity: 0 }}
            animate={{ width: 140, height: 140, opacity: 1 }}
            transition={{ duration: 1, ease: "easeOut" }}
            style={{ position: "absolute" }}
          />
          <h1 className="font-display text-3xl font-bold tracking-[0.4em] text-snow z-10">
            {title.replace(" OS", "")}
            {title.includes("OS") && <span className="text-brass"> OS</span>}
            <span className="inline-block w-2 h-6 bg-brass ml-1 animate-pulse align-middle" />
          </h1>
          <div className="mt-32 font-mono text-[11px] text-fog space-y-1 h-28 text-center">
            {lines.filter(Boolean).map((l, i) => (
              <motion.p key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}>
                {l.replace("ONLINE", "").replace("STANDBY", "")}
                {l.includes("ONLINE") && <span className="text-sage">ONLINE</span>}
                {l.includes("STANDBY") && <span className="text-brass">STANDBY</span>}
              </motion.p>
            ))}
          </div>
          <p className="absolute bottom-8 text-fog text-xs font-mono">click to skip</p>
        </motion.div>
      ) : (
        <motion.div key="fade" className="fixed inset-0 z-50 bg-ink pointer-events-none" initial={{ opacity: 1 }} animate={{ opacity: 0 }} transition={{ duration: 0.7 }} />
      )}
    </AnimatePresence>
  );
}
