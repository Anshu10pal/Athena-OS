import { Mic, Send, Square, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
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

  return (
    <div className="h-full flex flex-col bg-ink">
      {!chatting ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
          <p className="mx-auto max-w-md text-fog text-sm leading-relaxed">
            Ask Athena to teach a topic, plan your roadmap, or recall what you've learned.{" "}
            <span className="text-fog/70">(Ctrl+K works anywhere.)</span>
          </p>
        </div>
      ) : (
        <div className="text-center pt-4 pb-1 shrink-0">
          <p className="font-mono text-[11px] tracking-[0.3em] text-accent uppercase">{orb.state}</p>
        </div>
      )}

      {chatting && (
        <div className="flex-1 overflow-y-auto flex flex-col justify-end">
          <div className="max-w-3xl mx-auto px-6 py-4 flex flex-col gap-3 w-full">
            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              const streaming = isLast && m.role === "assistant" && orb.state === "speaking" && !voiceReplies;
              return (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap leading-relaxed border ${
                      m.role === "user" ? "bg-accent/10 border-accent/30 text-snow" : "card text-snow"
                    }`}
                  >
                    {m.intent && m.role === "assistant" && (
                      <p className="text-[10px] font-mono tracking-wider text-accent uppercase mb-1.5">{m.intent} agent</p>
                    )}
                    {m.content || <span className="text-fog">…</span>}
                    {streaming && <span className="inline-block w-1.5 h-3.5 bg-accent ml-0.5 align-middle animate-pulse" />}
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      <div className="shrink-0 px-6 pb-6 pt-2">
        <div className="max-w-3xl mx-auto flex items-center gap-2 card p-2.5">
          <button
            onClick={toggleMic}
            title={recording ? "Stop (auto-stops on pause)" : "Speak to Athena"}
            className={`rounded-lg p-2 border transition-colors ${
              recording ? "bg-danger text-ink border-danger" : "bg-panel2 text-accent border-line hover:border-accent/50"
            }`}
          >
            {recording ? <Square size={18} /> : <Mic size={18} />}
          </button>
          <button
            onClick={() => setVoiceReplies((v) => !v)}
            title={voiceReplies ? "Voice replies on" : "Voice replies off"}
            className={`rounded-lg p-2 border border-line bg-panel2 transition-colors ${voiceReplies ? "text-accent" : "text-fog"}`}
          >
            {voiceReplies ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
          <input
            className="flex-1 bg-transparent border-none outline-none text-snow text-sm px-1.5"
            placeholder="Ask Athena anything…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button onClick={() => send()} disabled={orb.state === "thinking"} className="btn-accent px-3.5 py-2.5 rounded-lg">
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
