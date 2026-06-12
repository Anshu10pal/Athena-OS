import { Database, Flame, Hexagon, MessageCircle, Mic2, Presentation, Route, Settings as SettingsIcon, Sparkles, Speech, Target, Volume2, VolumeX } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { isMuted, toggleMute } from "../lib/sound";
import { useAuth } from "../store/auth";
import HudTelemetry from "./HudTelemetry";
import ParticleField from "./ParticleField";
import StatusStrip from "./StatusStrip";

const nav = [
  { to: "/", label: "Hub", icon: Hexagon },
  { to: "/chat", label: "Athena", icon: MessageCircle },
  { to: "/roadmap", label: "Roadmap", icon: Route },
  { to: "/missions", label: "Missions", icon: Target },
  { to: "/interview", label: "Interview Arena", icon: Mic2 },
  { to: "/oratory", label: "Oratory Deck", icon: Speech },
  { to: "/presentation", label: "Presentation Arena", icon: Presentation },
  { to: "/vault", label: "Knowledge Vault", icon: Database },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [muted, setMuted] = useState(isMuted());
  const xp = user?.xp ?? 0;
  const level = Math.floor(xp / 500) + 1;
  const intoLevel = ((xp % 500) / 500) * 100;

  return (
    <div className="min-h-screen flex relative">
      <ParticleField />
      <aside
        className="w-60 shrink-0 border-r border-line flex flex-col relative overflow-hidden"
        style={{ zIndex: 10, background: "linear-gradient(180deg, #131825 0%, #0E121B 55%, #0B0E14 100%)" }}
      >
        {/* faint constellation decoration */}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ opacity: 0.12 }} aria-hidden="true">
          <circle cx="30" cy="120" r="1.5" fill="#D4B36A" />
          <circle cx="180" cy="200" r="1" fill="#D4B36A" />
          <circle cx="90" cy="340" r="1.5" fill="#D4B36A" />
          <circle cx="200" cy="480" r="1" fill="#D4B36A" />
          <circle cx="50" cy="560" r="1.5" fill="#D4B36A" />
          <line x1="30" y1="120" x2="180" y2="200" stroke="#D4B36A" strokeWidth="0.5" />
          <line x1="180" y1="200" x2="90" y2="340" stroke="#D4B36A" strokeWidth="0.5" />
          <line x1="90" y1="340" x2="200" y2="480" stroke="#D4B36A" strokeWidth="0.5" />
        </svg>

        <div className="px-5 py-6 relative">
          <div className="flex items-center gap-2.5">
            <span className="relative grid place-items-center w-7 h-7">
              <span className="absolute inset-0 rounded-full border border-dashed border-brass/50 animate-[spin_9s_linear_infinite]" />
              <span className="w-2.5 h-2.5 rounded-full bg-brass" />
            </span>
            <div>
              <h1 className="font-display font-bold text-lg tracking-wide leading-none">
                ATHENA <span className="text-brass">OS</span>
              </h1>
              <p className="text-fog text-[10px] font-mono mt-1 tracking-wider">ADAPTIVE TERMINAL</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-0.5 relative">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `group flex items-center gap-2.5 pl-3 pr-3 py-2 rounded-lg text-sm transition-all relative ${
                  isActive ? "bg-panel2/80 text-brass" : "text-fog hover:text-snow hover:bg-panel2/40"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <span className={`absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full transition-all ${isActive ? "bg-brass" : "bg-transparent group-hover:bg-line"}`} />
                  <item.icon size={15} className={isActive ? "text-brass" : "text-fog group-hover:text-snow"} />
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-line relative">
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-snow text-sm truncate">{user?.name}</p>
            <span className="font-mono text-[10px] text-brass">Lv {level}</span>
          </div>
          <div className="h-1 bg-panel2 rounded-full overflow-hidden mb-2">
            <div className="h-full bg-brass rounded-full transition-all" style={{ width: `${intoLevel}%` }} />
          </div>
          <button onClick={logout} className="text-fog hover:text-ember text-[11px] font-mono">
            SIGN OUT
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0 relative" style={{ zIndex: 10 }}>
        <header className="h-14 border-b border-line flex items-center justify-between gap-5 px-6 text-sm bg-ink/60 backdrop-blur-sm">
          <StatusStrip />
          <div className="flex items-center gap-5">
            <span className="flex items-center gap-1.5 text-fog">
              <Flame size={15} className="text-ember" />
              <span className="font-mono">{user?.streak ?? 0}</span> day streak
            </span>
            <span className="flex items-center gap-1.5 text-fog">
              <Sparkles size={15} className="text-brass" />
              <span className="font-mono">{xp}</span> XP
            </span>
            <button onClick={() => setMuted(toggleMute())} className="text-fog hover:text-brass" title={muted ? "Unmute sounds" : "Mute sounds"}>
              {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto px-8 py-6">
          <Outlet />
        </main>
      </div>
      <HudTelemetry />
    </div>
  );
}
