import { Mic, Send, Square, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import VoiceOrb from "../components/VoiceOrb";
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

  return (
    <div className="w-full max-w-[1100px] mx-auto h-full flex flex-col">
      <div className="flex flex-col items-center pb-4">
        <VoiceOrb state={orb.state} size={96} />
        <p className="text-fog text-xs mt-2 font-mono uppercase tracking-widest">{orb.state}</p>
      </div>
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.length === 0 && (
          <p className="text-center text-fog text-sm pt-8">
            Ask Athena to teach a topic, plan your roadmap, or recall what you've learned. (Ctrl+K works anywhere.)
          </p>
        )}
        {messages.map((m, i) => {
          const isLast = i === messages.length - 1;
          const streaming = isLast && m.role === "assistant" && orb.state === "speaking" && !voiceReplies;
          return (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${
                  m.role === "user" ? "bg-panel2 border border-line" : "card"
                }`}
              >
                {m.intent && m.role === "assistant" && (
                  <p className="text-[10px] font-mono uppercase tracking-widest text-brass mb-1.5">{m.intent} agent</p>
                )}
                {m.content || <span className="text-fog">…</span>}
                {streaming && <span className="inline-block w-1.5 h-3.5 bg-brass ml-0.5 align-middle animate-pulse" />}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2 pt-2 border-t border-line">
        <button
          onClick={toggleMic}
          className={`rounded-lg border border-line px-3 transition-colors ${
            recording ? "bg-ember text-ink" : "bg-panel2 text-fog hover:text-brass"
          }`}
          title={recording ? "Stop now (auto-stops after a 2s pause)" : "Speak to Athena — stops itself when you pause"}
        >
          {recording ? <Square size={18} /> : <Mic size={18} />}
        </button>
        <button
          onClick={() => setVoiceReplies((v) => !v)}
          className={`rounded-lg border border-line px-3 transition-colors ${voiceReplies ? "text-brass" : "text-fog"} bg-panel2 hover:text-brass`}
          title={voiceReplies ? "Voice replies on" : "Voice replies off"}
        >
          {voiceReplies ? <Volume2 size={18} /> : <VolumeX size={18} />}
        </button>
        <input
          className="input"
          placeholder="Ask Athena anything…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn-brass" onClick={() => send()}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
