import { LogOut, Settings as SettingsIcon, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { isMuted, toggleMute } from "../lib/sound";
import { useAuth } from "../store/auth";

export default function UserProfileMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [muted, setMuted] = useState(isMuted());
  const wrapRef = useRef<HTMLDivElement>(null);
  const location = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const xp = user?.xp ?? 0;
  const level = Math.floor(xp / 500) + 1;
  const initial = (user?.name || "?").trim().charAt(0).toUpperCase();

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="profile-trigger"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Account menu"
        title="Account"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="profile-avatar">{initial}</span>
        {user?.name?.split(" ")[0]}
      </button>
      <div className={`profile-menu ${open ? "open" : ""}`} role="menu">
        <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--edge)" }}>
          <p style={{ fontSize: 13.5, color: "var(--fg)" }}>{user?.name}</p>
          <p style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--fg-3)", marginTop: 3 }}>
            LEVEL {level} &middot; {xp} XP
          </p>
        </div>
        <Link to="/settings" role="menuitem" onClick={() => setOpen(false)}>
          <SettingsIcon size={15} /> Settings
        </Link>
        <button type="button" role="menuitem" onClick={() => setMuted(toggleMute())}>
          {muted ? <VolumeX size={15} /> : <Volume2 size={15} />} {muted ? "Unmute sounds" : "Mute sounds"}
        </button>
        <button type="button" role="menuitem" className="danger" onClick={logout}>
          <LogOut size={15} /> Sign out
        </button>
      </div>
    </div>
  );
}
