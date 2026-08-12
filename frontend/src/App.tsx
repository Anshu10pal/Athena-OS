import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import CommandPalette from "./components/CommandPalette";
import Layout from "./components/Layout";
import LevelUpOverlay from "./components/LevelUpOverlay";
import Chat from "./pages/Chat";
import Hub from "./pages/Hub";
import InterviewArena from "./pages/InterviewArena";
import Login from "./pages/Login";
import Missions from "./pages/Missions";
import ModuleDetail from "./pages/ModuleDetail";
import OratoryDeck from "./pages/OratoryDeck";
import PresentationArena from "./pages/PresentationArena";
import Communication from "./pages/Communication";
import Review from "./pages/Review";
import Achievements from "./pages/Achievements";
import Repos from "./pages/Repos";
import RepoDetail from "./pages/RepoDetail";
import { ViewBoundary } from "./components/ViewBoundary";
import Roadmap from "./pages/Roadmap";
import Settings from "./pages/Settings";
import Vault from "./pages/Vault";
import { useAuth } from "./store/auth";

function EscToHub() {
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === "Escape" && location.pathname !== "/" && tag !== "INPUT" && tag !== "TEXTAREA") {
        navigate("/");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate, location.pathname]);
  return null;
}

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <div className="min-h-screen grid place-items-center text-fog">Loading ATHENA OS…</div>;
  return (
    <BrowserRouter>
      <EscToHub />
      <CommandPalette />
      <LevelUpOverlay />
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
        <Route element={user ? <Layout /> : <Navigate to="/login" />}>
          <Route path="/" element={<Hub />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/roadmap" element={<Roadmap />} />
          <Route path="/modules/:slug" element={<ModuleDetail />} />
          <Route path="/missions" element={<Missions />} />
          <Route path="/interview" element={<InterviewArena />} />
          <Route path="/oratory" element={<OratoryDeck />} />
          <Route path="/presentation" element={<PresentationArena />} />
          <Route path="/vault" element={<Vault />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/review" element={<Review />} />
          <Route path="/communication" element={<Communication />} />
          <Route path="/achievements" element={<Achievements />} />
          <Route path="/repos" element={<Repos />} />
          {/* Nested boundaries, not one or the other.
              ViewBoundary (in RepoDetail) catches a PANEL throwing and names
              the panel. This one catches RepoDetail's OWN render body -- the
              `visible` memo, filter derivation, sorting, `files.length` --
              which sits above every per-view boundary and is where the
              scale-dependent derivation happens. The seven inner boundaries
              could not have caught a throw there, which is the shape of the
              blank page that was reported.
              It lives in the route `element`, so it renders OUTSIDE
              RepoDetail's tree and inside <Layout/> -- the nav and
              back-to-repos stay usable when it fires. */}
          <Route
            path="/repos/:id"
            element={
              <ViewBoundary name="Repository" backTo={{ href: "/repos", label: "back to repos" }}>
                <RepoDetail />
              </ViewBoundary>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
