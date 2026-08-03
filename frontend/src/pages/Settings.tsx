import { useState } from "react";
import { api, getToken } from "../lib/api";
import { DecryptText } from "../lib/fx";
import { useAuth } from "../store/auth";
import Toggle from "../components/Toggle";

const VOICES = [
  { id: "en-IN-NeerjaNeural", label: "Neerja — Indian English, female" },
  { id: "en-IN-PrabhatNeural", label: "Prabhat — Indian English, male" },
  { id: "en-US-AriaNeural", label: "Aria — US, female (default)" },
  { id: "en-US-GuyNeural", label: "Guy — US, male" },
  { id: "en-US-JennyNeural", label: "Jenny — US, female" },
  { id: "en-GB-SoniaNeural", label: "Sonia — British, female" },
  { id: "en-AU-NatashaNeural", label: "Natasha — Australian, female" },
];

export default function Settings() {
  const { user, refresh } = useAuth();
  const [voice, setVoice] = useState(user?.voice ?? "en-US-AriaNeural");
  const [targetRole, setTargetRole] = useState(user?.target_role ?? "");
  const [level, setLevel] = useState(user?.experience_level ?? "beginner");
  const [savedMsg, setSavedMsg] = useState("");
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [testing, setTesting] = useState(false);
  const [wakeWord, setWakeWord] = useState(localStorage.getItem("athena_wakeword") === "1");

  const saveProfile = async () => {
    await api("/api/profile", { method: "PATCH", body: JSON.stringify({ voice, target_role: targetRole, experience_level: level }) });
    await refresh();
    setSavedMsg("Saved.");
    setTimeout(() => setSavedMsg(""), 2000);
  };

  const testVoice = async () => {
    setTesting(true);
    try {
      await api("/api/profile", { method: "PATCH", body: JSON.stringify({ voice }) });
      const res = await fetch("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ text: "Hello Anshuman. This is how I will sound from now on." }),
      });
      if (res.ok) new Audio(URL.createObjectURL(await res.blob())).play();
      else alert("Server TTS unavailable — install edge-tts in the backend venv");
    } finally {
      setTesting(false);
    }
  };

  const changePassword = async () => {
    setPwMsg("");
    try {
      await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: curPw, new_password: newPw }) });
      setPwMsg("Password updated.");
      setCurPw("");
      setNewPw("");
    } catch (e: any) {
      setPwMsg(e.message);
    }
  };

  return (
    <div className="w-full max-w-2xl space-y-6">
      <h2 className="font-display text-2xl font-semibold text-snow"><DecryptText text="Settings" /></h2>

      <section className="card p-5 space-y-3">
        <p className="font-mono text-[10px] tracking-[0.3em] text-fog">ATHENA'S VOICE</p>
        <select className="input" value={voice} onChange={(e) => setVoice(e.target.value)}>
          {VOICES.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <div className="flex gap-2">
          <button className="btn-accent" onClick={saveProfile}>Save</button>
          <button className="border border-line rounded-lg px-4 text-sm text-fog hover:text-accent hover:border-accent/40 transition-colors" onClick={testVoice} disabled={testing}>
            {testing ? "Speaking…" : "Test voice"}
          </button>
          {savedMsg && <span className="text-accent text-xs self-center font-mono">{savedMsg}</span>}
        </div>
        <p className="font-mono text-[10px] text-fog">one voice, everywhere — chat replies, briefings, every spoken word</p>
      </section>

      <section className="card p-5 space-y-3">
        <p className="font-mono text-[10px] tracking-[0.3em] text-fog">PROFILE</p>
        <input className="input" placeholder="Target role (drives roadmaps, missions, interview tailoring)" value={targetRole} onChange={(e) => setTargetRole(e.target.value)} />
        <select className="input" value={level} onChange={(e) => setLevel(e.target.value)}>
          {["beginner", "intermediate", "advanced", "architect"].map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <button className="btn-accent" onClick={saveProfile}>Save profile</button>
      </section>

      <section className="card p-5 space-y-3">
        <p className="font-mono text-[10px] tracking-[0.3em] text-fog">WAKE WORD</p>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-snow">Say “Hey Athena” to open chat</p>
            <p className="text-fog text-[11px] mt-0.5">Uses your browser’s speech recognition (Chrome/Edge). Listens only while ATHENA is open.</p>
          </div>
          <Toggle
            checked={wakeWord}
            onChange={(v) => { setWakeWord(v); localStorage.setItem("athena_wakeword", v ? "1" : "0"); }}
            label="Toggle wake word"
          />
        </div>
        <p className="font-mono text-[10px] text-fog">reload the page after enabling so the listener starts</p>
      </section>

      <section className="card p-5 space-y-3">
        <p className="font-mono text-[10px] tracking-[0.3em] text-fog">CHANGE PASSWORD</p>
        <input className="input" type="password" placeholder="Current password" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
        <input className="input" type="password" placeholder="New password (min 6 chars)" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        <div className="flex gap-3 items-center">
          <button className="btn-accent" onClick={changePassword} disabled={!curPw || !newPw}>Update password</button>
          {pwMsg && <span className={`text-xs font-mono ${pwMsg.includes("updated") ? "text-accent" : "text-danger"}`}>{pwMsg}</span>}
        </div>
      </section>
    </div>
  );
}
