import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

const COMMANDS = [
  { label: "Return to Hub", path: "/" },
  { label: "Talk to Athena", path: "/chat" },
  { label: "Open Roadmap", path: "/roadmap" },
  { label: "Daily Missions", path: "/missions" },
  { label: "Start an Interview", path: "/interview" },
  { label: "Interview from a Job Description", path: "/arena" },
  { label: "Oratory Deck — speak", path: "/oratory" },
  { label: "Analyze a Presentation", path: "/presentation" },
  { label: "Search Knowledge Vault", path: "/vault" },
  { label: "Communication Gym — listening, speaking, reading, writing", path: "/communication" },
  { label: "Review Queue — spaced repetition", path: "/review" },
  { label: "Achievements", path: "/achievements" },
  { label: "Settings — voice, wake word & password", path: "/settings" },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
        setQuery("");
        setCursor(0);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const filtered = useMemo(
    () => COMMANDS.filter((c) => c.label.toLowerCase().includes(query.toLowerCase())),
    [query]
  );

  const run = (idx: number) => {
    if (filtered[idx]) {
      navigate(filtered[idx].path);
    } else if (query.trim()) {
      navigate(`/chat?q=${encodeURIComponent(query.trim())}`);
    }
    setOpen(false);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-40 flex items-start justify-center pt-32"
          style={{ background: "rgba(15,23,42,0.7)" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setOpen(false)}
        >
          <motion.div
            className="w-full max-w-lg card overflow-hidden"
            initial={{ y: -12, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            onClick={(e) => e.stopPropagation()}
          >
            <input
              autoFocus
              className="w-full bg-transparent px-4 py-3 text-snow placeholder-fog focus:outline-none border-b border-line font-body"
              placeholder="Type a command, or ask Athena anything…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCursor(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, filtered.length - 1));
                if (e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
                if (e.key === "Enter") run(cursor);
              }}
            />
            <div className="py-1">
              {filtered.map((c, i) => (
                <button
                  key={c.path}
                  className={`w-full text-left px-4 py-2 text-sm ${i === cursor ? "bg-panel2 text-accent" : "text-fog"}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => run(i)}
                >
                  {c.label}
                </button>
              ))}
              {filtered.length === 0 && query.trim() && (
                <button className="w-full text-left px-4 py-2 text-sm text-accent" onClick={() => run(-1)}>
                  Ask Athena: "{query}"
                </button>
              )}
            </div>
            <p className="px-4 py-2 border-t border-line text-[10px] font-mono text-fog">↑↓ navigate · Enter run · Esc close</p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
