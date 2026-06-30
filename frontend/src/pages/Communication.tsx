import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { AnimatedNumber, DecryptText } from "../lib/fx";
import { unlock } from "../lib/sound";
import { useAuth } from "../store/auth";

type Modality = "listening" | "speaking" | "reading" | "writing";
type Difficulty = "Beginner" | "Intermediate" | "Advanced";

const ACCENT: Record<Modality, string> = { listening: "#5FD3E0", speaking: "#D4B36A", reading: "#8B7FD6", writing: "#7FB58C" };
const TILES: { mode: Modality; icon: string; desc: string }[] = [
  { mode: "listening", icon: "∿", desc: "Athena reads a passage aloud — then tests reception, inference & recall." },
  { mode: "speaking", icon: "◉", desc: "Impromptu speech with pacing, fillers, structure & delivery scoring." },
  { mode: "reading", icon: "▤", desc: "Timed read of a generated passage — WPM, comprehension, vocab & inference." },
  { mode: "writing", icon: "✎", desc: "Prompt → typed response. Grammar, vocab, structure, precision, clarity, tone." },
];

interface Radar { listening: number | null; speaking: number | null; reading: number | null; writing: number | null; communication: number | null; }
interface WritingPrompt { prompt: string; target_words: number; register: string; difficulty: string; }
interface ScoreCell { value: number; source: "measured" | "evaluated"; }
interface WritingResult {
  overall: number;
  scores: Record<string, ScoreCell>;
  feedback: string; tip: string;
  grammar_fixes: { original: string; corrected: string }[];
  vocab_upgrades: { used: string; try: string; note: string }[];
  review_added: number;
  new_badges: { code: string; title: string }[];
}

export default function Communication() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [view, setView] = useState<Modality | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty>("Intermediate");
  const [radar, setRadar] = useState<Radar | null>(null);

  useEffect(() => { api<Radar>("/api/communication/radar").then(setRadar).catch(() => {}); }, []);

  if (view === "writing") return <Writing difficulty={difficulty} onBack={() => { setView(null); api<Radar>("/api/communication/radar").then(setRadar).catch(() => {}); }} refresh={refresh} />;
  if (view === "speaking") return <Speaking radar={radar} onBack={() => setView(null)} onLaunch={() => navigate("/oratory")} />;
  if (view === "reading") return <Reading difficulty={difficulty} onBack={() => { setView(null); api<Radar>("/api/communication/radar").then(setRadar).catch(() => {}); }} refresh={refresh} />;
  if (view === "listening") return <Listening difficulty={difficulty} onBack={() => { setView(null); api<Radar>("/api/communication/radar").then(setRadar).catch(() => {}); }} refresh={refresh} />;

  // radar geometry (center 110, max r 90): listening=top, speaking=right, reading=bottom, writing=left
  const pt = (v: number | null, axis: "t" | "r" | "b" | "l") => {
    const r = ((v ?? 0) / 100) * 90;
    if (axis === "t") return `110,${110 - r}`;
    if (axis === "r") return `${110 + r},110`;
    if (axis === "b") return `110,${110 + r}`;
    return `${110 - r},110`;
  };
  const poly = radar ? `${pt(radar.listening, "t")} ${pt(radar.speaking, "r")} ${pt(radar.reading, "b")} ${pt(radar.writing, "l")}` : "110,110 110,110 110,110 110,110";

  return (
    <div className="w-full max-w-none space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h2 className="font-display text-2xl font-semibold text-snow"><DecryptText text="Communication Gym" /></h2>
          <p className="text-fog text-sm mt-1 font-mono">four facets of one skill · generated fresh each session</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[9.5px] text-fog/60 tracking-widest mr-1">DIFFICULTY</span>
          <div className="flex gap-1 bg-panel/60 p-1 rounded-lg border border-line">
            {(["Beginner", "Intermediate", "Advanced"] as Difficulty[]).map((d) => (
              <button key={d} onClick={() => setDifficulty(d)}
                className={`text-[11px] px-3 py-1.5 rounded-md transition-colors ${difficulty === d ? "bg-cyan/15 text-cyanbright" : "text-fog hover:text-softwhite"}`}>{d}</button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1.55fr_1fr] gap-5">
        <div className="grid grid-cols-2 gap-4">
          {TILES.map((t) => (
            <button key={t.mode} onClick={() => setView(t.mode)}
              className="card p-4 text-left transition-transform hover:-translate-y-1 hover:border-cyan/50 group">
              <div className="text-2xl mb-2" style={{ color: ACCENT[t.mode], textShadow: `0 0 11px ${ACCENT[t.mode]}99` }}>{t.icon}</div>
              <p className="text-[15px] font-medium text-snow capitalize">{t.mode}</p>
              <p className="text-[11px] text-fog mt-1.5 leading-snug min-h-[46px]">{t.desc}</p>
              <div className="flex items-center gap-2 mt-2.5 font-mono text-[9.5px] text-fog">
                {(() => { const v = radar?.[t.mode] ?? null; return (
                  <>
                    <span>{v != null ? `last ${v}` : "not yet"}</span>
                    <div className="flex-1 h-[3px] bg-line rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${v ?? 0}%`, background: ACCENT[t.mode] }} />
                    </div>
                  </>
                ); })()}
              </div>
            </button>
          ))}
        </div>

        <div className="card p-5 flex flex-col items-center justify-center">
          <p className="font-mono text-[10px] tracking-widest text-fog">COMMUNICATION</p>
          <p className="font-display text-4xl font-semibold text-snow mt-1 mb-1">{radar?.communication != null ? <AnimatedNumber value={radar.communication} /> : "—"}</p>
          <svg viewBox="0 0 220 220" className="w-[210px] h-[210px]" role="img" aria-label="Communication radar">
            {[90, 60, 30].map((r) => (
              <polygon key={r} points={`110,${110 - r} ${110 + r},110 110,${110 + r} ${110 - r},110`} fill="none" stroke="#1E2738" strokeWidth="1" />
            ))}
            <line x1="110" y1="20" x2="110" y2="200" stroke="#1E2738" strokeWidth="1" />
            <line x1="20" y1="110" x2="200" y2="110" stroke="#1E2738" strokeWidth="1" />
            <polygon points={poly} fill="rgba(95,211,224,0.15)" stroke="#5FD3E0" strokeWidth="1.5" />
            <circle cx={pt(radar?.listening ?? 0, "t").split(",")[0]} cy={pt(radar?.listening ?? 0, "t").split(",")[1]} r="3" fill={ACCENT.listening} />
            <circle cx={pt(radar?.speaking ?? 0, "r").split(",")[0]} cy={pt(radar?.speaking ?? 0, "r").split(",")[1]} r="3" fill={ACCENT.speaking} />
            <circle cx={pt(radar?.reading ?? 0, "b").split(",")[0]} cy={pt(radar?.reading ?? 0, "b").split(",")[1]} r="3" fill={ACCENT.reading} />
            <circle cx={pt(radar?.writing ?? 0, "l").split(",")[0]} cy={pt(radar?.writing ?? 0, "l").split(",")[1]} r="3" fill={ACCENT.writing} />
            <text x="110" y="12" textAnchor="middle" fill={ACCENT.listening} fontSize="9" fontFamily="monospace">LISTEN</text>
            <text x="207" y="113" textAnchor="middle" fill={ACCENT.speaking} fontSize="9" fontFamily="monospace">SPEAK</text>
            <text x="110" y="216" textAnchor="middle" fill={ACCENT.reading} fontSize="9" fontFamily="monospace">READ</text>
            <text x="14" y="113" textAnchor="middle" fill={ACCENT.writing} fontSize="9" fontFamily="monospace">WRITE</text>
          </svg>
        </div>
      </div>
      <p className="text-center font-mono text-[9.5px] tracking-widest text-fog/50">↑ CLICK ANY TILE TO OPEN ITS DRILL</p>
    </div>
  );
}

function ComingSoon({ mode, onBack }: { mode: Modality; onBack: () => void }) {
  return (
    <div className="w-full max-w-2xl mx-auto">
      <button onClick={onBack} className="text-fog text-sm hover:text-snow mb-4">← back to gym</button>
      <div className="card p-8 text-center space-y-3">
        <div className="text-3xl" style={{ color: ACCENT[mode] }}>{mode === "listening" ? "∿" : "▤"}</div>
        <p className="text-snow text-lg capitalize">{mode} drill</p>
        <p className="text-fog text-sm">Coming in the next drop. Writing is live now — it's the deepest of the four and proves the pattern.</p>
      </div>
    </div>
  );
}

function Writing({ difficulty, onBack, refresh }: { difficulty: Difficulty; onBack: () => void; refresh: () => void }) {
  const [prompt, setPrompt] = useState<WritingPrompt | null>(null);
  const [response, setResponse] = useState("");
  const [result, setResult] = useState<WritingResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => { setResult(null); setResponse(""); api<WritingPrompt>("/api/communication/writing/prompt", { method: "POST", body: JSON.stringify({ difficulty }) }).then(setPrompt).catch(() => {}); };
  useEffect(() => { load(); }, []);

  const words = response.trim() ? response.trim().split(/\s+/).length : 0;

  const analyze = async () => {
    if (!prompt) return;
    setBusy(true);
    try {
      const r = await api<WritingResult & { error?: string }>("/api/communication/writing/analyze", {
        method: "POST",
        body: JSON.stringify({ prompt: prompt.prompt, response, register: prompt.register, difficulty }),
      });
      if ((r as any).error) { alert((r as any).error); return; }
      setResult(r);
      if (r.overall >= 75) unlock();
      refresh();
    } finally { setBusy(false); }
  };

  const ORDER = ["grammar", "vocabulary", "structure", "precision", "clarity", "tone"];
  const color = (v: number) => (v >= 75 ? "#7FB58C" : v >= 55 ? "#D4B36A" : "#D98A6A");

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      <button onClick={onBack} className="text-fog text-sm hover:text-snow">← back to gym</button>
      <p className="font-mono text-[10px] tracking-[0.2em]" style={{ color: ACCENT.writing }}>WRITING · {difficulty.toUpperCase()}</p>

      <div className="card p-4">
        <p className="font-mono text-[10px] text-fog tracking-wide">PROMPT · target {prompt?.target_words ?? "…"} words · register: {prompt?.register ?? "…"}</p>
        <p className="text-[15px] text-snow mt-2 leading-relaxed min-h-[48px]">{prompt?.prompt ?? "Generating a prompt…"}</p>
      </div>

      {!result && (
        <>
          <textarea rows={6} className="input" placeholder="Type your response… (Athena scores it live and locally)" value={response} onChange={(e) => setResponse(e.target.value)} />
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-fog">{words} / {prompt?.target_words ?? 0} words</span>
            <div className="flex gap-2">
              <button className="btn-cyan text-sm" onClick={load} disabled={busy}>New prompt</button>
              <button className="btn-brass" onClick={analyze} disabled={busy || words < 5}>{busy ? "Analyzing…" : "Analyze response"}</button>
            </div>
          </div>
        </>
      )}

      {result && (
        <div className="space-y-4">
          <div className="card p-5 text-center">
            <p className="font-mono text-[10px] tracking-[0.3em] text-fog">WRITING SCORE</p>
            <p className="font-display text-5xl mt-1" style={{ color: color(result.overall) }}><AnimatedNumber value={result.overall} /></p>
          </div>

          <div className="grid sm:grid-cols-2 gap-x-5 gap-y-3">
            {ORDER.map((k) => {
              const cell = result.scores[k];
              return (
                <div key={k}>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-softwhite capitalize">{k} <span className="font-mono text-[8px] text-fog/60 tracking-wider">{cell.source.toUpperCase()}</span></span>
                    <span className="font-mono" style={{ color: color(cell.value) }}>{cell.value}</span>
                  </div>
                  <div className="h-1.5 bg-panel2 rounded-full overflow-hidden mt-1.5">
                    <div className="h-full rounded-full" style={{ width: `${cell.value}%`, background: color(cell.value) }} />
                  </div>
                </div>
              );
            })}
          </div>

          {result.feedback && (
            <div className="card p-4 border-cyan/25">
              <p className="text-[13px] text-softwhite leading-relaxed"><b className="text-cyanbright">Athena:</b> {result.feedback}</p>
              {result.tip && <p className="text-[12px] text-fog mt-2">💡 {result.tip}</p>}
              {result.review_added > 0 && <p className="font-mono text-[9.5px] mt-2" style={{ color: ACCENT.writing }}>↻ {result.review_added} item{result.review_added > 1 ? "s" : ""} added to Review Queue</p>}
            </div>
          )}

          {result.grammar_fixes?.length > 0 && (
            <div className="card p-4">
              <p className="font-mono text-[10px] tracking-widest text-fog mb-2">GRAMMAR FIXES</p>
              {result.grammar_fixes.map((f, i) => (
                <p key={i} className="text-[12px] mb-1"><span className="text-ember line-through">{f.original}</span> <span className="text-fog">→</span> <span className="text-sage">{f.corrected}</span></p>
              ))}
            </div>
          )}

          {result.vocab_upgrades?.length > 0 && (
            <div className="card p-4">
              <p className="font-mono text-[10px] tracking-widest text-fog mb-2">VOCABULARY UPGRADES</p>
              {result.vocab_upgrades.map((v, i) => (
                <p key={i} className="text-[12px] mb-1"><span className="text-fog">{v.used}</span> <span className="text-fog">→</span> <span className="text-cyan">{v.try}</span> <span className="text-fog/60">— {v.note}</span></p>
              ))}
            </div>
          )}

          <div className="flex justify-center gap-2">
            <button className="btn-cyan" onClick={onBack}>Done</button>
            <button className="btn-brass" onClick={load}>Another drill</button>
          </div>
        </div>
      )}
    </div>
  );
}

interface RQuestion { q: string; options: string[]; answer: number; type: string; term?: string; detail?: string; }
interface RPassage { passage: string; word_count: number; target_seconds: number; questions: RQuestion[]; difficulty: string; }
interface RResult { overall: number; wpm: number; dimensions: Record<string, number | null>; review_added: number; }

function Reading({ difficulty, onBack, refresh }: { difficulty: Difficulty; onBack: () => void; refresh: () => void }) {
  const [data, setData] = useState<RPassage | null>(null);
  const [phase, setPhase] = useState<"loading" | "reading" | "quiz" | "result">("loading");
  const [startTs, setStartTs] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [wpm, setWpm] = useState(0);
  const [qIdx, setQIdx] = useState(0);
  const [picks, setPicks] = useState<number[]>([]);
  const [result, setResult] = useState<RResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setPhase("loading"); setResult(null); setQIdx(0);
    api<RPassage>("/api/communication/reading/passage", { method: "POST", body: JSON.stringify({ difficulty }) })
      .then((d) => { setData(d); setPicks(new Array(d.questions.length).fill(-1)); setPhase("reading"); setStartTs(Date.now()); })
      .catch(() => {});
  };
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (phase !== "reading") return;
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startTs) / 1000)), 1000);
    return () => clearInterval(t);
  }, [phase, startTs]);

  const doneReading = () => {
    const secs = Math.max(1, (Date.now() - startTs) / 1000);
    setWpm(Math.round((data!.word_count / secs) * 60));
    setPhase("quiz");
  };

  const pick = (o: number) => {
    const next = [...picks]; next[qIdx] = o; setPicks(next);
    if (qIdx < data!.questions.length - 1) setTimeout(() => setQIdx(qIdx + 1), 150);
  };

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api<RResult>("/api/communication/reading/submit", {
        method: "POST",
        body: JSON.stringify({ difficulty, wpm, word_count: data!.word_count, questions: data!.questions, picks }),
      });
      setResult(r); setPhase("result");
      if (r.overall >= 75) unlock();
      refresh();
    } finally { setBusy(false); }
  };

  const color = (v: number) => (v >= 75 ? "#7FB58C" : v >= 55 ? "#D4B36A" : "#D98A6A");
  const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      <button onClick={onBack} className="text-fog text-sm hover:text-snow">← back to gym</button>
      <p className="font-mono text-[10px] tracking-[0.2em]" style={{ color: ACCENT.reading }}>READING · {difficulty.toUpperCase()}</p>

      {phase === "loading" && <div className="card p-8 text-center text-fog text-sm">Generating a passage…</div>}

      {phase === "reading" && data && (
        <>
          <div className="card p-5">
            <div className="flex justify-between font-mono text-[10px] text-fog mb-2">
              <span>GENERATED PASSAGE · {data.word_count} words</span>
              <span style={{ color: ACCENT.reading }}>⏱ {mmss(elapsed)}</span>
            </div>
            <p className="text-[14px] text-softwhite leading-[1.8] whitespace-pre-wrap">{data.passage}</p>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-fog">read at your natural pace — WPM is measured</span>
            <button className="btn-brass" onClick={doneReading}>Done reading → quiz</button>
          </div>
        </>
      )}

      {phase === "quiz" && data && (
        <div className="card p-5 space-y-4">
          <div className="flex justify-between font-mono text-[10px] text-fog">
            <span>Q{qIdx + 1} / {data.questions.length} · {data.questions[qIdx].type.replace("_", " ")}</span>
            <span style={{ color: ACCENT.reading }}>{wpm} WPM</span>
          </div>
          <div className="h-1 bg-panel2 rounded-full overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${(picks.filter((p) => p >= 0).length / data.questions.length) * 100}%`, background: ACCENT.reading }} />
          </div>
          <p className="text-sm text-snow leading-relaxed">{data.questions[qIdx].q}</p>
          <div className="space-y-2">
            {data.questions[qIdx].options.map((o, i) => (
              <button key={i} onClick={() => pick(i)}
                className={`w-full text-left text-xs px-3 py-2.5 rounded-lg border transition-colors ${picks[qIdx] === i ? "border-cyan bg-cyan/10 text-snow" : "border-line bg-panel2 text-fog hover:border-cyan/40 hover:text-snow"}`}>
                <span className="font-mono text-cyan mr-2">{String.fromCharCode(65 + i)}</span>{o}
              </button>
            ))}
          </div>
          <div className="flex justify-between">
            <div className="flex gap-1">
              {data.questions.map((_, i) => (
                <button key={i} onClick={() => setQIdx(i)} className="w-6 h-6 rounded text-[10px] font-mono"
                  style={{ background: i === qIdx ? "rgba(95,211,224,0.2)" : picks[i] >= 0 ? "rgba(127,181,140,0.15)" : "#10171F", color: picks[i] >= 0 ? "#7FB58C" : "#9AA4B4" }}>{i + 1}</button>
              ))}
            </div>
            <button className="btn-brass" disabled={picks.some((p) => p < 0) || busy} onClick={submit}>{busy ? "Scoring…" : "Submit quiz"}</button>
          </div>
        </div>
      )}

      {phase === "result" && result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="card p-5 text-center">
              <p className="font-mono text-[10px] tracking-[0.3em] text-fog">READING SCORE</p>
              <p className="font-display text-5xl mt-1" style={{ color: color(result.overall) }}><AnimatedNumber value={result.overall} /></p>
            </div>
            <div className="card p-5 text-center">
              <p className="font-mono text-[10px] tracking-[0.3em] text-fog">READING SPEED <span className="text-[8px]">MEASURED</span></p>
              <p className="font-display text-5xl mt-1 text-snow"><AnimatedNumber value={result.wpm} /> <span className="text-lg text-fog">wpm</span></p>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-x-5 gap-y-3">
            {Object.entries(result.dimensions).filter(([, v]) => v !== null).map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-[11px]">
                  <span className="text-softwhite capitalize">{k.replace("_", " ")} <span className="font-mono text-[8px] text-fog/60 tracking-wider">GRADED</span></span>
                  <span className="font-mono" style={{ color: color(v as number) }}>{v}</span>
                </div>
                <div className="h-1.5 bg-panel2 rounded-full overflow-hidden mt-1.5">
                  <div className="h-full rounded-full" style={{ width: `${v}%`, background: color(v as number) }} />
                </div>
              </div>
            ))}
          </div>
          {result.review_added > 0 && (
            <div className="card p-4 border-cyan/25">
              <p className="font-mono text-[9.5px]" style={{ color: ACCENT.writing }}>↻ {result.review_added} vocab item{result.review_added > 1 ? "s" : ""} added to Review Queue</p>
            </div>
          )}
          <div className="flex justify-center gap-2">
            <button className="btn-cyan" onClick={onBack}>Done</button>
            <button className="btn-brass" onClick={load}>Another passage</button>
          </div>
        </div>
      )}
    </div>
  );
}

interface LQuestion { q: string; options: string[]; answer: number; type: string; term?: string; detail?: string; }
interface LPassage { audio_b64: string | null; passage?: string; questions: LQuestion[]; difficulty: string; tts_unavailable: boolean; }
interface LResult { overall: number; dimensions: Record<string, number | null>; review_added: number; }

function Listening({ difficulty, onBack, refresh }: { difficulty: Difficulty; onBack: () => void; refresh: () => void }) {
  const [data, setData] = useState<LPassage | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "playing" | "quiz" | "result">("loading");
  const [played, setPlayed] = useState(false);
  const [qIdx, setQIdx] = useState(0);
  const [picks, setPicks] = useState<number[]>([]);
  const [result, setResult] = useState<LResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setPhase("loading"); setResult(null); setQIdx(0); setPlayed(false);
    api<LPassage>("/api/communication/listening/passage", { method: "POST", body: JSON.stringify({ difficulty }) })
      .then((d) => { setData(d); setPicks(new Array(d.questions.length).fill(-1)); setPhase("ready"); })
      .catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const play = () => {
    if (played || !data) return;
    setPhase("playing");
    if (data.audio_b64) {
      const audio = new Audio(`data:audio/mpeg;base64,${data.audio_b64}`);
      audio.onended = () => { setPlayed(true); setPhase("quiz"); };
      audio.play().catch(() => { setPlayed(true); setPhase("quiz"); });
    } else if (data.passage && "speechSynthesis" in window) {
      // fallback: browser reads the withheld text aloud (never shown on screen)
      const u = new SpeechSynthesisUtterance(data.passage);
      u.onend = () => { setPlayed(true); setPhase("quiz"); };
      window.speechSynthesis.speak(u);
    } else {
      setPlayed(true); setPhase("quiz");
    }
  };

  const pick = (o: number) => {
    const next = [...picks]; next[qIdx] = o; setPicks(next);
    if (qIdx < data!.questions.length - 1) setTimeout(() => setQIdx(qIdx + 1), 150);
  };

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api<LResult>("/api/communication/listening/submit", {
        method: "POST", body: JSON.stringify({ difficulty, questions: data!.questions, picks }),
      });
      setResult(r); setPhase("result");
      if (r.overall >= 75) unlock();
      refresh();
    } finally { setBusy(false); }
  };

  const color = (v: number) => (v >= 75 ? "#7FB58C" : v >= 55 ? "#D4B36A" : "#D98A6A");

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      <button onClick={onBack} className="text-fog text-sm hover:text-snow">← back to gym</button>
      <p className="font-mono text-[10px] tracking-[0.2em]" style={{ color: ACCENT.listening }}>LISTENING · {difficulty.toUpperCase()}</p>

      {phase === "loading" && <div className="card p-8 text-center text-fog text-sm">Preparing the passage…</div>}

      {(phase === "ready" || phase === "playing") && (
        <div className="card p-8 text-center space-y-3">
          <div className="text-4xl" style={{ color: ACCENT.listening, textShadow: "0 0 16px rgba(95,211,224,0.6)" }}>∿</div>
          <p className="text-[14px] text-softwhite max-w-md mx-auto leading-relaxed">
            Athena will read a passage aloud <b>once</b> — you can't replay it. Listen closely, then answer.
          </p>
          {data?.tts_unavailable && <p className="font-mono text-[9.5px] text-ember">audio service blocked — using your browser's voice</p>}
          <button className="btn-brass mt-2" disabled={phase === "playing"} onClick={play}>
            {phase === "playing" ? "▶ Playing… listen" : "▶ Play passage (once)"}
          </button>
          <p className="font-mono text-[9.5px] text-fog/60">reception &amp; inference scored separately</p>
        </div>
      )}

      {phase === "quiz" && data && (
        <div className="card p-5 space-y-4">
          <div className="flex justify-between font-mono text-[10px] text-fog">
            <span>Q{qIdx + 1} / {data.questions.length} · {data.questions[qIdx].type}</span>
            <span style={{ color: ACCENT.listening }}>audio complete</span>
          </div>
          <div className="h-1 bg-panel2 rounded-full overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${(picks.filter((p) => p >= 0).length / data.questions.length) * 100}%`, background: ACCENT.listening }} />
          </div>
          <p className="text-sm text-snow leading-relaxed">{data.questions[qIdx].q}</p>
          <div className="space-y-2">
            {data.questions[qIdx].options.map((o, i) => (
              <button key={i} onClick={() => pick(i)}
                className={`w-full text-left text-xs px-3 py-2.5 rounded-lg border transition-colors ${picks[qIdx] === i ? "border-cyan bg-cyan/10 text-snow" : "border-line bg-panel2 text-fog hover:border-cyan/40 hover:text-snow"}`}>
                <span className="font-mono text-cyan mr-2">{String.fromCharCode(65 + i)}</span>{o}
              </button>
            ))}
          </div>
          <div className="flex justify-between">
            <div className="flex gap-1">
              {data.questions.map((_, i) => (
                <button key={i} onClick={() => setQIdx(i)} className="w-6 h-6 rounded text-[10px] font-mono"
                  style={{ background: i === qIdx ? "rgba(95,211,224,0.2)" : picks[i] >= 0 ? "rgba(127,181,140,0.15)" : "#10171F", color: picks[i] >= 0 ? "#7FB58C" : "#9AA4B4" }}>{i + 1}</button>
              ))}
            </div>
            <button className="btn-brass" disabled={picks.some((p) => p < 0) || busy} onClick={submit}>{busy ? "Scoring…" : "Submit quiz"}</button>
          </div>
        </div>
      )}

      {phase === "result" && result && (
        <div className="space-y-4">
          <div className="card p-5 text-center">
            <p className="font-mono text-[10px] tracking-[0.3em] text-fog">LISTENING SCORE</p>
            <p className="font-display text-5xl mt-1" style={{ color: color(result.overall) }}><AnimatedNumber value={result.overall} /></p>
          </div>
          <div className="grid sm:grid-cols-2 gap-x-5 gap-y-3">
            {Object.entries(result.dimensions).filter(([, v]) => v !== null).map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-[11px]">
                  <span className="text-softwhite capitalize">{k} <span className="font-mono text-[8px] text-fog/60 tracking-wider">GRADED</span></span>
                  <span className="font-mono" style={{ color: color(v as number) }}>{v}</span>
                </div>
                <div className="h-1.5 bg-panel2 rounded-full overflow-hidden mt-1.5">
                  <div className="h-full rounded-full" style={{ width: `${v}%`, background: color(v as number) }} />
                </div>
              </div>
            ))}
          </div>
          {result.review_added > 0 && (
            <div className="card p-4 border-cyan/25">
              <p className="font-mono text-[9.5px]" style={{ color: ACCENT.writing }}>↻ {result.review_added} item{result.review_added > 1 ? "s" : ""} added to Review Queue</p>
            </div>
          )}
          <div className="flex justify-center gap-2">
            <button className="btn-cyan" onClick={onBack}>Done</button>
            <button className="btn-brass" onClick={load}>Another passage</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Speaking({ radar, onBack, onLaunch }: { radar: Radar | null; onBack: () => void; onLaunch: () => void }) {
  return (
    <div className="w-full max-w-2xl mx-auto space-y-4">
      <button onClick={onBack} className="text-fog text-sm hover:text-snow">← back to gym</button>
      <p className="font-mono text-[10px] tracking-[0.2em]" style={{ color: ACCENT.speaking }}>SPEAKING · ORATORY DECK</p>
      <div className="card p-8 text-center space-y-3">
        <div className="text-3xl" style={{ color: ACCENT.speaking, textShadow: "0 0 14px rgba(212,179,106,0.6)" }}>◉</div>
        <p className="text-snow text-lg">The Speaking pillar</p>
        <p className="text-fog text-sm max-w-md mx-auto leading-relaxed">
          Impromptu speaking with topic draw, a 30-second think timer, and live scoring of pacing,
          fillers, structure and delivery. Your speeches feed this gym's radar automatically.
        </p>
        {radar?.speaking != null && (
          <p className="font-mono text-[11px]" style={{ color: ACCENT.speaking }}>last speaking score · {radar.speaking}</p>
        )}
        <button className="btn-brass mt-2" onClick={onLaunch}>Draw a topic → start speaking</button>
      </div>
    </div>
  );
}
