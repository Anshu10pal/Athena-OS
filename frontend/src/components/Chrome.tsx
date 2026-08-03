import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { HUD_H, NAV_H } from "../lib/layout";
import { useAuth } from "../store/auth";
import HudStrip from "./HudStrip";
import ToolsMenu from "./ToolsMenu";
import UserProfileMenu from "./UserProfileMenu";

export default function Chrome() {
  const { pathname } = useLocation();
  const { user } = useAuth();
  const isHome = pathname === "/";
  const [stuck, setStuck] = useState(!isHome);

  useEffect(() => {
    if (!isHome) {
      setStuck(true);
      return;
    }
    const onScroll = () => setStuck(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [isHome]);

  const megaTop = (isHome ? NAV_H + HUD_H : NAV_H) + 8;

  return (
    <div className={`chrome ${stuck ? "stuck" : ""}`}>
      <div style={{ maxWidth: 1680, margin: "0 auto", paddingInline: "var(--gutter)" }}>
        <nav className="nav">
          <Link className="brand" to="/">
            <i />
            <b>ATHENA</b>
            <span>OS</span>
          </Link>
          <div className="nav-links">
            <ToolsMenu top={megaTop} />
            <Link to="/#progress">Progress</Link>
            <Link to="/#grid">Tools grid</Link>
          </div>
          <div className="nav-right">
            <span className="pill">{user?.streak ?? 0} DAY STREAK</span>
            <span className="pill">{user?.xp ?? 0} XP</span>
            {!isHome && <HudStrip variant="compact" />}
            <UserProfileMenu />
          </div>
        </nav>
        {isHome && <HudStrip variant="full" />}
      </div>
    </div>
  );
}
