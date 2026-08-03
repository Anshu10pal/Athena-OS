import { useRef, useState } from "react";
import { Link } from "react-router-dom";

interface Tile {
  cat: "learn" | "practice" | "reinforce";
  to: string;
  label: string;
  desc: string;
  meta: string;
  span2?: boolean;
}

const TILES: Tile[] = [
  {
    cat: "learn", to: "/chat", label: "Athena", span2: true,
    desc: "Talk through a topic and get taught back. She tracks what confused you and turns it into review cards without being asked.",
    meta: "Last used 2h ago",
  },
  { cat: "learn", to: "/roadmap", label: "Roadmap", desc: "A drillable path through any subject.", meta: "38% complete" },
  { cat: "learn", to: "/vault", label: "Knowledge Vault", desc: "Everything you've saved, searchable.", meta: "0 notes" },
  {
    cat: "practice", to: "/communication", label: "Communication Gym", span2: true,
    desc: "Four rooms — writing, reading, listening, speaking. The oratory deck lives inside speaking. Each room scores you against your last attempt, not a rubric you'll never see.",
    meta: "Speaking is lagging",
  },
  { cat: "practice", to: "/presentation", label: "Presentation Arena", desc: "Deliver to a room that interrupts.", meta: "0 runs" },
  { cat: "practice", to: "/interview", label: "Interview Arena", desc: "Mock interviews that follow up.", meta: "0 sat" },
  {
    cat: "reinforce", to: "/review", label: "Review Queue", span2: true,
    desc: "What's due, in the order it's due. Cards come from your own sessions, scheduled by how badly you fumbled them the first time.",
    meta: "3 due · ~6 min",
  },
  { cat: "reinforce", to: "/missions", label: "Missions", desc: "Small daily objectives, no filler.", meta: "2 of 3" },
  { cat: "reinforce", to: "/achievements", label: "Achievements", desc: "Streaks and badges worth keeping.", meta: "Lv 1" },
];

const FILTERS = ["all", "learn", "practice", "reinforce"] as const;
type Filter = (typeof FILTERS)[number];

export default function ToolsBento() {
  const [active, setActive] = useState<Filter>("all");
  const tileRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const busyRef = useRef(false);

  const filter = (f: Filter) => {
    setActive(f);
    if (busyRef.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tiles = tileRefs.current.filter(Boolean) as HTMLAnchorElement[];
    const hide: HTMLAnchorElement[] = [];
    const show: HTMLAnchorElement[] = [];
    tiles.forEach((t, i) => {
      const wants = f === "all" || TILES[i].cat === f;
      const isOut = t.classList.contains("gone");
      if (wants && isOut) show.push(t);
      if (!wants && !isOut) hide.push(t);
    });
    if (!hide.length && !show.length) return;

    if (reduce) {
      hide.forEach((t) => t.classList.add("gone"));
      show.forEach((t) => t.classList.remove("gone"));
      return;
    }

    busyRef.current = true;
    hide.forEach((t, i) => {
      t.style.transitionDelay = `${i * 35}ms`;
      t.classList.add("leaving");
    });
    const wait = hide.length ? 280 + hide.length * 35 : 0;

    setTimeout(() => {
      hide.forEach((t) => {
        t.classList.add("gone");
        t.classList.remove("leaving");
        t.style.transitionDelay = "";
      });
      show.forEach((t) => {
        t.classList.add("entering");
        t.classList.remove("gone");
      });
      // force reflow so the "entering" starting state is committed before we remove it
      void document.body.offsetHeight;
      show.forEach((t, i) => {
        t.style.transitionDelay = `${i * 60}ms`;
        requestAnimationFrame(() => t.classList.remove("entering"));
      });
      setTimeout(() => {
        show.forEach((t) => {
          t.style.transitionDelay = "";
        });
        busyRef.current = false;
      }, 340 + show.length * 60);
    }, wait);
  };

  return (
    <section className="band" id="grid">
      <div className="sec-head rise">
        <div>
          <span className="sec-tag">Nine tools, three jobs</span>
          <h2>Everything Athena can do</h2>
          <p>Filter by what you're trying to get done, or reach any of them from the Tools menu.</p>
        </div>
        <div className="chips">
          {FILTERS.map((f) => (
            <button key={f} type="button" className={`chip ${active === f ? "on" : ""}`} onClick={() => filter(f)}>
              {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="bento">
        {TILES.map((t, i) => (
          <Link
            key={t.to}
            ref={(el) => (tileRefs.current[i] = el)}
            className={`tile rise ${t.span2 ? "span2" : ""}`}
            data-c={t.cat}
            to={t.to}
          >
            <span className="cat">{t.cat.charAt(0).toUpperCase() + t.cat.slice(1)}</span>
            <h3>{t.label}</h3>
            <p>{t.desc}</p>
            <span className="meter">
              <span>{t.meta}</span>
              <span className="arrow">Open &rarr;</span>
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
