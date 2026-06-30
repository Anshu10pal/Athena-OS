import { Mic, Send, Square, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import GeoCore from "../components/GeoCore";
import { getToken, streamChat } from "../lib/api";
import { startHum, stopHum } from "../lib/sound";
import { useAudioReactive } from "../lib/useMicLevel";
import { useOrb } from "../store/orb";

interface Msg {
  role: "user" | "assistant";
  content: string;
  intent?: string;
}

export default function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [recording, setRecording] = useState(false);
  const [voiceReplies, setVoiceReplies] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const sentFromUrl = useRef(false);
  const mouse = useRef({ x: 0, y: 0 });
  const orb = useOrb();
  const { attach, detach } = useAudioReactive();
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const q = params.get("q");
    if (q && !sentFromUrl.current) {
      sentFromUrl.current = true;
      setParams({}, { replace: true });
      send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const speakBrowser = (text: string) => {
    // Guaranteed fallback: the browser's built-in speech engine (always available, offline)
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text.slice(0, 800));
      const voices = window.speechSynthesis.getVoices();
      utter.voice = voices.find((v) => /aria|zira|female|natural/i.test(v.name) && v.lang.startsWith("en")) || voices.find((v) => v.lang.startsWith("en")) || null;
      utter.rate = 1.02;
      utter.onstart = () => orb.setState("speaking");
      utter.onend = () => orb.setState("idle");
      utter.onerror = () => orb.setState("idle");
      window.speechSynthesis.speak(utter);
    } catch {
      orb.setState("idle");
    }
  };

  const speakAnswer = async (text: string) => {
    try {
      const res = await fetch("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ text: text.slice(0, 600) }),
      });
      if (!res.ok) {
        console.warn("Server TTS unavailable, using browser voice");
        speakBrowser(text);
        return;
      }
      const blob = await res.blob();
      const audio = new Audio(URL.createObjectURL(blob));
      audioRef.current = audio;
      orb.setState("speaking");
      attach(audio);
      audio.onended = () => {
        detach();
        orb.setState("idle");
      };
      await audio.play().catch(() => {
        detach();
        speakBrowser(text); // autoplay blocked -> synthesis (runs in user-gesture-free mode)
      });
    } catch {
      speakBrowser(text);
    }
  };

  const send = async (text?: string, viaVoice = false) => {
    const message = (text ?? input).trim();
    if (!message || orb.state === "thinking") return;
    setInput("");
    const history = messages.map(({ role, content }) => ({ role, content }));
    setMessages((m) => [...m, { role: "user", content: message }, { role: "assistant", content: "" }]);
    orb.setState("thinking");
    startHum();
    const t0 = performance.now();
    let firstToken = 0;
    let tokens = 0;
    let answer = "";
    try {
      await streamChat(message, history.slice(-10), (e) => {
        if (e.type === "token") {
          if (!firstToken) {
            firstToken = performance.now();
            stopHum();
            orb.setState("speaking");
            orb.setMetrics({ ...orb.metrics, latencyMs: Math.round(firstToken - t0) });
          }
          tokens++;
          answer += e.text;
          const elapsed = (performance.now() - firstToken) / 1000;
          if (elapsed > 0.5) orb.setMetrics({ intent: orb.metrics.intent, latencyMs: Math.round(firstToken - t0), tps: Math.round(tokens / elapsed) });
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { ...copy[copy.length - 1], content: answer };
            return copy;
          });
        } else if (e.type === "meta") {
          orb.setMetrics({ ...orb.metrics, intent: e.intent });
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { ...copy[copy.length - 1], intent: e.intent };
            return copy;
          });
        } else if (e.type === "error") {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { ...copy[copy.length - 1], content: `Something went wrong: ${e.message}` };
            return copy;
          });
        }
      });
    } finally {
      stopHum();
      if ((voiceReplies || viaVoice) && answer) speakAnswer(answer);
      else orb.setState("idle");
    }
  };

  const toggleMic = async () => {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      attach(stream);
      const recorder = new MediaRecorder(stream);

      // Hands-free: auto-stop after 2s of silence (once speech has started)
      let spoke = false;
      let silentSince = 0;
      const SILENCE_MS = 2000;
      const THRESHOLD = 0.06;
      const vad = window.setInterval(() => {
        const level = orb.audioLevel.current;
        if (level > THRESHOLD) {
          spoke = true;
          silentSince = 0;
        } else if (spoke) {
          silentSince += 150;
          if (silentSince >= SILENCE_MS && recorder.state === "recording") {
            window.clearInterval(vad);
            recorder.stop();
          }
        }
      }, 150);
      recorder.addEventListener("stop", () => window.clearInterval(vad));
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        detach();
        setRecording(false);
        orb.setState("thinking");
        const blob = new Blob(chunks, { type: "audio/webm" });
        const form = new FormData();
        form.append("file", blob, "speech.webm");
        try {
          const res = await fetch("/api/voice/transcribe", {
            method: "POST",
            headers: { Authorization: `Bearer ${getToken()}` },
            body: form,
          });
          if (res.status === 501) {
            orb.setState("idle");
            alert("Local voice not installed yet — see README 'Voice setup'. Using text for now.");
            return;
          }
          const { text } = await res.json();
          if (text) send(text, true); // voice in -> voice out, conversation mode
          else orb.setState("idle");
        } catch {
          orb.setState("idle");
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      orb.setState("listening");
    } catch {
      alert("Microphone permission denied.");
    }
  };

  const chatting = messages.length > 0;
  const onMove = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    mouse.current = { x: (e.clientX - r.left) / r.width - 0.5, y: (e.clientY - r.top) / r.height - 0.5 };
  };

  return (
    <div onMouseMove={onMove} style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <GeoCore mouse={mouse} dim={chatting} />

      {/* state label, top-center */}
      <div style={{ position: "absolute", top: chatting ? 14 : "26%", left: 0, right: 0, textAlign: "center", zIndex: 10, pointerEvents: "none", transition: "top .5s" }}>
        <p style={{ fontFamily: "monospace", fontSize: 11, letterSpacing: 6, color: "#5FD3E0", textTransform: "uppercase" }}>{orb.state}</p>
        {!chatting && (
          <p style={{ margin: "14px auto 0", maxWidth: 460, color: "#E6ECF4", fontSize: 15, lineHeight: 1.7 }}>
            Ask Athena to teach a topic, plan your roadmap, or recall what you've learned. <span style={{ color: "#9AA4B4" }}>(Ctrl+K works anywhere.)</span>
          </p>
        )}
      </div>

      {/* messages — translucent glass column over the dimmed core */}
      {chatting && (
        <div style={{ position: "absolute", top: 60, bottom: 96, left: 0, right: 0, overflowY: "auto", zIndex: 10 }}>
          <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 24px", display: "flex", flexDirection: "column", gap: 14 }}>
            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              const streaming = isLast && m.role === "assistant" && orb.state === "speaking" && !voiceReplies;
              return (
                <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                  <div style={{
                    maxWidth: "82%", borderRadius: 14, padding: "12px 16px", fontSize: 14, whiteSpace: "pre-wrap", lineHeight: 1.6,
                    background: m.role === "user" ? "rgba(95,211,224,0.1)" : "rgba(16,23,33,0.66)",
                    backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
                    border: m.role === "user" ? "1px solid rgba(95,211,224,0.35)" : "1px solid rgba(212,179,106,0.22)",
                    color: "#fff",
                  }}>
                    {m.intent && m.role === "assistant" && (
                      <p style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: 2, color: "#5FD3E0", textTransform: "uppercase", margin: "0 0 6px" }}>{m.intent} agent</p>
                    )}
                    {m.content || <span style={{ color: "#9AA4B4" }}>…</span>}
                    {streaming && <span style={{ display: "inline-block", width: 6, height: 14, background: "#5FD3E0", marginLeft: 2, verticalAlign: "middle" }} className="animate-pulse" />}
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      {/* docked input bar */}
      <div style={{ position: "absolute", bottom: 22, left: 0, right: 0, zIndex: 20, display: "flex", justifyContent: "center", padding: "0 24px" }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 10, width: "100%", maxWidth: 760,
          background: "rgba(12,17,25,0.7)", backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)",
          border: "1px solid rgba(95,211,224,0.3)", borderRadius: 16, padding: "10px 12px",
          boxShadow: "0 0 30px rgba(95,211,224,0.12)",
        }}>
          <button onClick={toggleMic} title={recording ? "Stop (auto-stops on pause)" : "Speak to Athena"}
            style={{ borderRadius: 10, border: "1px solid rgba(95,211,224,0.25)", padding: "8px 10px", cursor: "pointer",
              background: recording ? "#D98A6A" : "rgba(95,211,224,0.08)", color: recording ? "#06080C" : "#5FD3E0" }}>
            {recording ? <Square size={18} /> : <Mic size={18} />}
          </button>
          <button onClick={() => setVoiceReplies((v) => !v)} title={voiceReplies ? "Voice replies on" : "Voice replies off"}
            style={{ borderRadius: 10, border: "1px solid rgba(95,211,224,0.25)", padding: "8px 10px", cursor: "pointer",
              background: "rgba(95,211,224,0.08)", color: voiceReplies ? "#5FD3E0" : "#9AA4B4" }}>
            {voiceReplies ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
          <input
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#fff", fontSize: 14, padding: "0 6px" }}
            placeholder="Ask Athena anything…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button onClick={() => send()} disabled={orb.state === "thinking"}
            style={{ borderRadius: 12, border: "none", cursor: "pointer", padding: "9px 14px",
              background: "linear-gradient(135deg,#D4B36A,#b8954a)", color: "#06080C", boxShadow: "0 0 18px rgba(212,179,106,0.35)" }}>
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
