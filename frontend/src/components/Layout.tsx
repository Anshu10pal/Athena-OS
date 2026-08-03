import { Outlet, useLocation } from "react-router-dom";
import { NAV_H } from "../lib/layout";
import Chrome from "./Chrome";

export default function Layout() {
  const { pathname } = useLocation();
  const isHome = pathname === "/";
  const isChat = pathname === "/chat";

  return (
    <div className="min-h-screen bg-ink">
      <Chrome />
      {isHome ? (
        // Hub.tsx owns its own top spacing via .hero's padding-top (nav-h + hud-h)
        <div>
          <Outlet />
        </div>
      ) : isChat ? (
        <main className="fixed inset-x-0 bottom-0 overflow-hidden" style={{ top: NAV_H }}>
          <Outlet />
        </main>
      ) : (
        <main className="px-8 pb-6" style={{ paddingTop: NAV_H + 24 }}>
          <Outlet />
        </main>
      )}
    </div>
  );
}
