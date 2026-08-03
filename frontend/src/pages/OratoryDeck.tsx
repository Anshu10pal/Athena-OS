import { useEffect, useRef, useState } from "react";
import VoiceOrb from "../components/VoiceOrb";
import { api, getToken } from "../lib/api";
import { AnimatedNumber, DecryptText } from "../lib/fx";
import { useAudioReactive } from "../lib/useMicLevel";
import { useAuth } from "../store/auth";
import { useOrb } from "../store/orb";

type Phase = "setup" | "topic" | "think" | "speak" | "analyzing" | "result";

interface Analysis {
  transcript: string;
  metrics: {
    duration_secs: number;
    target_secs: number;
    words: number;
    wpm: number;
    filler_count: number;
    filler_rate_per_min: number;
    filler_breakdown: { word: string; count: number }[];
    hedge_breakdown: { word: string; count: number }[];
    weak_words: { word: string; count: number }[];
    wpm_timeline: { t: number; wpm: number }[];
    talk_ratio: number;
    crutch_words: { word: string; count: number }[];
    pause_count: number;
    stall_pauses: number;
    longest_pause_secs: number;
  };
  scores: {
    structure?: number;
    relevance?: number;
    vocabulary?: number;
    delivery?: number;
    feedback?: string;
    tip?: string;
    grammar_fixes?: { original: string; corrected: string }[];
    vocab_suggestions?: { used: string; try: string }[];
  };
  xp_gained: number;
  improved: boolean;
}

export default function OratoryDeck() {
  const { refresh } = useAuth();
  const orb = useOrb();
  const { attach, detach } = useAudioReactive();
  const [phase, setPhase] = useState<Phase>("setup");
  const [mode, setMode] = useState("classic");
  const [target, setTarget] = useState(60);
  const [topic, setTopic] = useState("");
  const [hint, setHint] = useState("");
  const [countdown, setCountdown] = useState(30);
  const [elapsed, setElapsed] = useState(0);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [history, setHistory] = useState<{ filler_rate: number | null }[]>([]);
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number>(0);

  useEffect(() => {
    api<any[]>("/api/oratory/history").then(setHistory).catch(() => {});
    return () => {
      window.clearInterval(timerRef.current);
      recorderRef.current?.state === "recording" && recorderRef.current.stop();
    };
  }, []);

  const draw = async () => {
    setError("");
    setPhase("topic");
    try {
      const r = await api<{ topic: string; hint: string }>("/api/oratory/topic", { method: "POST", body: JSON.stringify({ mode }) });
      setTopic(r.topic);
      setHint(r.hint);
    } catch (e: any) {
      setError(e.message);
      setPhase("setup");
    }
  };

  const startThink = () => {
    setPhase("think");
    setCountdown(30);
    orb.setState("thinking");
    window.clearInterval(timerRef.current);
    const t0 = Date.now(); // timestamp stopwatch — immune to interval drift/double-fire
    timerRef.current = window.setInterval(() => {
      const left = 30 - Math.floor((Date.now() - t0) / 1000);
      setCountdown(Math.max(0, left));
      if (left <= 0) {
        window.clearInterval(timerRef.current);
        startSpeak();
      }
    }, 200);
  };

  const startSpeak = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      attach(stream);
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        detach();
        orb.setState("thinking");
        setPhase("analyzing");
        const form = new FormData();
        form.append("file", new Blob(chunks, { type: "audio/webm" }), "speech.webm");
        form.append("topic", topic);
        form.append("mode", mode);
        form.append("target_secs", String(target));
        try {
          const res = await fetch("/api/oratory/analyze", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: form });
          if (res.status === 501) throw new Error("Local STT not installed — run: pip install faster-whisper");
          if (!res.ok) throw new Error((await res.json()).detail || "Analysis failed");
          setAnalysis(await res.json());
          setPhase("result");
          refresh();
          api<any[]>("/api/oratory/history").then(setHistory).catch(() => {});
        } catch (e: any) {
          setError(e.message);
          setPhase("setup");
        } finally {
          orb.setState("idle");
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setPhase("speak");
      setElapsed(0);
      orb.setState("listening");
      window.clearInterval(timerRef.current);
      const t0 = Date.now(); // real stopwatch, not tick counting
      timerRef.current = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 200);
    } catch {
      setError("Microphone permission denied.");
      setPhase("setup");
    }
  };

  const stopSpeak = () => {
    window.clearInterval(timerRef.current);
    recorderRef.current?.stop();
  };

  // Toastmasters timing cards: green at min, amber at warning, red at limit
  const cardColor = phase !== "speak" ? "border-line" : elapsed >= target ? "border-danger" : elapsed >= target - 15 ? "border-warning" : elapsed >= Math.max(15, target - 45) ? "border-accent" : "border-line";

  return (
    <div className={`w-full max-w-none space-y-6`}>
      <div>
        <h2 className="font-display text-2xl font-semibold text-snow"><DecryptText text="Oratory deck" /></h2>
        <p className="text-fog text-sm mt-1 font-mono">table topics · 30s to think · speak your way to clarity</p>
      </div>
      {error && <p className="text-danger text-sm">{error}</p>}

      {phase === "setup" && (
        <div className="card p-5 space-y-4">
          <div>
            <p className="font-mono text-[10px] tracking-widest text-fog mb-2">MODE</p>
            <div className="flex gap-2">
              {["classic", "professional", "wildcard"].map((m) => (
                <button key={m} onClick={() => setMode(m)} className={`px-3 py-2 rounded-lg border text-xs capitalize transition-colors ${mode === m ? "border-accent text-accent bg-accent/10" : "border-line text-fog hover:text-snow"}`}>
                  {m}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="font-mono text-[10px] tracking-widest text-fog mb-2">SPEAKING TIME</p>
            <div className="flex gap-2">
              {[60, 120, 180].map((t) => (
                <button key={t} onClick={() => setTarget(t)} className={`px-3 py-2 rounded-lg border text-xs transition-colors ${target === t ? "border-accent text-accent bg-accent/10" : "border-line text-fog hover:text-snow"}`}>
                  {t / 60} min
                </button>
              ))}
            </div>
          </div>
          <button className="btn-accent w-full" onClick={draw}>Draw a topic</button>
          {history.length > 1 && (
            <div className="pt-2">
              <p className="font-mono text-[10px] tracking-widest text-fog mb-1.5">FILLER RATE TREND (PER MIN)</p>
              <svg viewBox="0 0 300 40" className="w-full h-10" role="img" aria-label="Filler rate over sessions">
                <polyline
                  fill="none" stroke="#22C55E" strokeWidth="1.5"
                  points={history.filter((h) => h.filler_rate != null).map((h, i, arr) => `${(i / Math.max(1, arr.length - 1)) * 290 + 5},${35 - Math.min(30, (h.filler_rate ?? 0) * 3)}`).join(" ")}
                />
              </svg>
            </div>
          )}
        </div>
      )}

      {phase === "topic" && (
        <div className="card p-6 text-center space-y-4">
          <p className="font-mono text-[10px] tracking-[0.3em] text-fog">YOUR TOPIC</p>
          <p className="font-display text-xl text-snow leading-snug min-h-14">{topic ? <DecryptText text={topic} speed={20} /> : "…"}</p>
          {hint && <p className="text-fog text-xs font-mono">angle: {hint}</p>}
          <button className="btn-accent" onClick={startThink} disabled={!topic}>Start 30s think timer</button>
        </div>
      )}

      {(phase === "think" || phase === "speak") && (
        <div className={`card p-6 text-center space-y-4 border-2 transition-colors ${cardColor}`}>
          <p className="font-display text-lg text-snow">{topic}</p>
          <div className="flex justify-center"><VoiceOrb state={orb.state} size={110} /></div>
          {phase === "think" ? (
            <>
              <p className="font-mono text-4xl text-accent">{countdown}</p>
              <p className="font-mono text-[10px] tracking-widest text-fog">THINK — NO NOTES</p>
              <button className="text-fog text-xs font-mono hover:text-snow" onClick={() => { window.clearInterval(timerRef.current); startSpeak(); }}>
                ready early — start speaking →
              </button>
            </>
          ) : (
            <>
              <p className="font-mono text-4xl text-snow">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</p>
              <p className="font-mono text-[10px] tracking-widest text-fog">SPEAKING · TARGET {target / 60} MIN · BORDER = TIMING CARD</p>
              <button className="btn-accent" onClick={stopSpeak}>Finish speech</button>
            </>
          )}
        </div>
      )}

      {phase === "analyzing" && (
        <div className="card p-8 text-center">
          <p className="text-fog text-sm font-mono animate-pulse">Transcribing verbatim · counting fillers · timing pauses…</p>
        </div>
      )}

      {phase === "result" && analysis && (
        <div className="space-y-4">
          <div className="card p-5 text-center">
            <p className="font-mono text-[10px] tracking-[0.3em] text-fog">AH-COUNTER REPORT · MEASURED</p>
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="fillers" value={analysis.metrics.filler_count} sub={`${analysis.metrics.filler_rate_per_min}/min`} />
              <Metric label="wpm" value={analysis.metrics.wpm} sub={analysis.metrics.wpm >= 110 && analysis.metrics.wpm <= 150 ? "sweet spot" : analysis.metrics.wpm > 150 ? "rushing" : "slow"} />
              <Metric label="stalls" value={analysis.metrics.stall_pauses} sub={`longest ${analysis.metrics.longest_pause_secs}s`} />
              <Metric label="duration" value={Math.round(analysis.metrics.duration_secs)} sub={`target ${analysis.metrics.target_secs}s`} />
            </div>
            <div className="mt-4">
              <p className="font-mono text-[9px] tracking-widest text-fog mb-1.5">YOUR FILLERS — EXACT COUNTS</p>
              {(analysis.metrics.filler_breakdown?.length ?? 0) > 0 ? (
                <div className="flex flex-wrap gap-1.5 justify-center">
                  {analysis.metrics.filler_breakdown.map((f) => (
                    <span key={f.word} className="font-mono text-[10px] text-danger border border-danger/30 bg-danger/10 rounded px-2 py-0.5">
                      "{f.word}" ×{f.count}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="font-mono text-[10px] text-accent">no core fillers detected this round — clean run</p>
              )}
            </div>
            {analysis.metrics.crutch_words.length > 0 && (
              <p className="font-mono text-[10px] text-fog mt-3">
                crutch words: {analysis.metrics.crutch_words.map((c) => `${c.word}×${c.count}`).join(" · ")}
              </p>
            )}
            {(analysis.metrics.hedge_breakdown?.length ?? 0) > 0 && (
              <div className="mt-3">
                <p className="font-mono text-[9px] tracking-widest text-fog mb-1.5">CONFIDENCE HEDGES — SOUND LESS SURE THAN YOU ARE</p>
                <div className="flex flex-wrap gap-1.5 justify-center">
                  {analysis.metrics.hedge_breakdown.map((h) => (
                    <span key={h.word} className="font-mono text-[10px] text-accent border border-accent/30 bg-accent/10 rounded px-2 py-0.5">
                      "{h.word}" ×{h.count}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(analysis.metrics.weak_words?.length ?? 0) > 0 && (
              <p className="font-mono text-[10px] text-fog mt-3">
                vague words: {analysis.metrics.weak_words.map((w) => `${w.word}×${w.count}`).join(" · ")} · talk ratio {Math.round((analysis.metrics.talk_ratio ?? 0) * 100)}%
              </p>
            )}
            {(analysis.metrics.wpm_timeline?.length ?? 0) > 2 && (
              <div className="mt-4">
                <p className="font-mono text-[9px] tracking-widest text-fog mb-1">PACE OVER TIME (WPM · 110–150 = SWEET SPOT)</p>
                <svg viewBox="0 0 300 50" className="w-full h-12" role="img" aria-label="Words per minute over time">
                  <rect x="0" y={50 - (150 / 220) * 50} width="300" height={((150 - 110) / 220) * 50} fill="rgba(34,197,94,0.12)" />
                  <polyline
                    fill="none" stroke="#22C55E" strokeWidth="1.5"
                    points={analysis.metrics.wpm_timeline.map((p, i, arr) => `${(i / Math.max(1, arr.length - 1)) * 294 + 3},${50 - Math.min(48, (p.wpm / 220) * 50)}`).join(" ")}
                  />
                </svg>
              </div>
            )}
            {analysis.improved && <p className="font-mono text-[10px] text-accent mt-2">IMPROVED OVER LAST SESSION +25 XP BONUS</p>}
          </div>

          <div className="card p-5">
            <p className="font-mono text-[10px] tracking-[0.3em] text-fog mb-3">EVALUATOR NOTES · AI JUDGED</p>
            <div className="space-y-2">
              {(["structure", "relevance", "vocabulary", "delivery"] as const).map((k) => (
                <div key={k} className="flex items-center gap-3 text-sm">
                  <span className="w-28 text-fog capitalize text-xs">{k}</span>
                  <div className="flex-1 h-1.5 bg-panel2 rounded-full overflow-hidden">
                    <div className="h-full bg-accent rounded-full" style={{ width: `${(analysis.scores[k] ?? 0) * 10}%` }} />
                  </div>
                  <span className="font-mono text-xs w-9 text-right">{analysis.scores[k] ?? "—"}/10</span>
                </div>
              ))}
            </div>
            {analysis.scores.feedback && <p className="text-fog text-xs mt-3 leading-relaxed">{analysis.scores.feedback}</p>}
            {analysis.scores.tip && <p className="text-accent text-xs mt-2 font-mono">next time → {analysis.scores.tip}</p>}
          </div>

          {(analysis.scores.grammar_fixes?.length ?? 0) > 0 && (
            <div className="card p-5">
              <p className="font-mono text-[10px] tracking-[0.3em] text-fog mb-3">GRAMMARIAN — CORRECTIONS</p>
              <div className="space-y-2">
                {analysis.scores.grammar_fixes!.map((g, i) => (
                  <div key={i} className="text-xs">
                    <p className="text-danger line-through">"{g.original}"</p>
                    <p className="text-accent mt-0.5">→ "{g.corrected}"</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {(analysis.scores.vocab_suggestions?.length ?? 0) > 0 && (
            <div className="card p-5">
              <p className="font-mono text-[10px] tracking-[0.3em] text-fog mb-3">VOCABULARY UPGRADES</p>
              <div className="flex flex-wrap gap-2">
                {analysis.scores.vocab_suggestions!.map((v, i) => (
                  <span key={i} className="font-mono text-[10px] border border-line rounded px-2 py-1">
                    <span className="text-fog">{v.used}</span> <span className="text-accent">→ {v.try}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          <details className="card p-4">
            <summary className="font-mono text-[10px] tracking-widest text-fog cursor-pointer">VERBATIM TRANSCRIPT</summary>
            <p className="text-xs text-fog mt-2 leading-relaxed whitespace-pre-wrap">{analysis.transcript}</p>
          </details>

          <button className="btn-accent w-full" onClick={() => { setAnalysis(null); setPhase("setup"); }}>
            Another round (+{analysis.xp_gained} XP earned)
          </button>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div>
      <p className="font-display text-2xl text-snow"><AnimatedNumber value={value} /></p>
      <p className="font-mono text-[9px] uppercase tracking-wider text-fog">{label}</p>
      <p className="font-mono text-[9px] text-accent mt-0.5">{sub}</p>
    </div>
  );
}
