import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

const GROUPS = [
  {
    title: "Learn",
    items: [
      { to: "/chat", label: "Athena", desc: "Ask, and be taught" },
      { to: "/roadmap", label: "Roadmap", desc: "Plan a path through a subject" },
      { to: "/vault", label: "Knowledge Vault", desc: "Everything you've saved" },
    ],
  },
  {
    title: "Practice",
    items: [
      { to: "/communication", label: "Communication Gym", desc: "Write, read, listen, speak" },
      { to: "/presentation", label: "Presentation Arena", desc: "Deliver to a live room" },
      { to: "/interview", label: "Interview Arena", desc: "Sit a mock interview" },
    ],
  },
  {
    title: "Reinforce",
    items: [
      { to: "/review", label: "Review Queue", desc: "What's due today" },
      { to: "/missions", label: "Missions", desc: "Daily objectives" },
      { to: "/achievements", label: "Achievements", desc: "Badges and streaks" },
    ],
  },
  {
    title: "Build",
    items: [{ to: "/repos", label: "Codebase Agent", desc: "Ingest a repo, get a ranked reading list" }],
  },
];

export default function ToolsMenu({ top }: { top: number }) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const flatLinks = GROUPS.flatMap((g) => g.items);

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!panelRef.current?.contains(e.target as Node) && !btnRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, flatLinks.length - 1));
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      }
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, flatLinks.length]);

  useEffect(() => {
    if (open) setCursor(0);
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className="tools-btn"
        aria-expanded={open}
        aria-controls="tools-mega"
        onClick={() => setOpen((o) => !o)}
      >
        Tools <span className="caret" />
      </button>
      <div id="tools-mega" ref={panelRef} className={`mega ${open ? "open" : ""}`} style={{ top }}>
        <div className="mega-grid">
          {GROUPS.map((g) => (
            <div key={g.title} className="mega-col">
              <h4>{g.title}</h4>
              {g.items.map((it) => {
                const idx = flatLinks.indexOf(it);
                return (
                  <Link
                    key={it.to}
                    to={it.to}
                    tabIndex={open ? 0 : -1}
                    style={idx === cursor ? { background: "var(--glass)" } : undefined}
                    onMouseEnter={() => setCursor(idx)}
                  >
                    <strong>{it.label}</strong>
                    <small>{it.desc}</small>
                  </Link>
                );
              })}
            </div>
          ))}
        </div>
        <div className="mega-foot">
          <Link to="/#grid">Browse all tools &rarr;</Link>
          <span>
            Search anywhere <span className="kbd">Ctrl K</span>
          </span>
        </div>
      </div>
    </>
  );
}
