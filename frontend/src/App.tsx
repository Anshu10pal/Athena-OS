import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import BootSequence from "./components/BootSequence";
import CommandPalette from "./components/CommandPalette";
import Layout from "./components/Layout";
import LevelUpOverlay from "./components/LevelUpOverlay";
import Chat from "./pages/Chat";
import Hub from "./pages/Hub";
import InterviewArena from "./pages/InterviewArena";
import Login from "./pages/Login";
import Missions from "./pages/Missions";
import OratoryDeck from "./pages/OratoryDeck";
import PresentationArena from "./pages/PresentationArena";
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
  const [booted, setBooted] = useState(() => sessionStorage.getItem("athena_booted") === "1");
  const finishBoot = () => {
    sessionStorage.setItem("athena_booted", "1");
    setBooted(true);
  };

  if (loading) return <div className="min-h-screen grid place-items-center text-fog">Loading ATHENA OS…</div>;
  return (
    <BrowserRouter>
      {!booted && <BootSequence onDone={finishBoot} />}
      <EscToHub />
      <CommandPalette />
      <LevelUpOverlay />
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
        <Route path="/" element={user ? <Hub /> : <Navigate to="/login" />} />
        <Route element={user ? <Layout /> : <Navigate to="/login" />}>
          <Route path="/chat" element={<Chat />} />
          <Route path="/roadmap" element={<Roadmap />} />
          <Route path="/missions" element={<Missions />} />
          <Route path="/interview" element={<InterviewArena />} />
          <Route path="/oratory" element={<OratoryDeck />} />
          <Route path="/presentation" element={<PresentationArena />} />
          <Route path="/vault" element={<Vault />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
