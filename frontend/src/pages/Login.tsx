import { useState } from "react";
import { useNavigate } from "react-router-dom";
import VoiceOrb from "../components/VoiceOrb";
import { api, setToken } from "../lib/api";
import { useAuth } from "../store/auth";

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const { refresh } = useAuth();

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (mode === "register") {
        const res = await api<{ access_token: string }>("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ name, email, password }),
        });
        setToken(res.access_token);
      } else {
        const form = new URLSearchParams({ username: email, password });
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: form,
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Login failed");
        setToken((await res.json()).access_token);
      }
      await refresh();
      navigate("/");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <VoiceOrb state="idle" size={110} />
          <h1 className="font-display text-2xl font-semibold mt-5 tracking-wide">
            ATHENA <span className="text-brass">OS</span>
          </h1>
          <p className="text-fog text-sm mt-1">Your personal AI academy</p>
        </div>
        <div className="card p-6 space-y-3">
          {mode === "register" && (
            <input className="input" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          <input className="input" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input
            className="input"
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          {error && <p className="text-ember text-sm">{error}</p>}
          <button className="btn-brass w-full" onClick={submit} disabled={busy}>
            {busy ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button
            className="text-fog text-sm hover:text-snow w-full"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
          >
            {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
