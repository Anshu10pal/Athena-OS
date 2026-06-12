import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, getToken } from "../lib/api";
import { AnimatedNumber, DecryptText } from "../lib/fx";
import { useAuth } from "../store/auth";

const ROLES = ["AI Engineer", "ML Engineer", "Data Scientist", "Architect", "Product Manager", "Behavioral"];
const SECS = 30;

interface MCQ {
  q: string;
  options: string[];
}

interface McqReview {
  q: string;
  options: string[];
  given: number;
  correct: number;
  ok: boolean;
}

interface Scores {
  communication: number;
  technical_accuracy: number;
  confidence: number;
  depth: number;
  leadership: number;
  mcq_score: number;
  feedback: string;
  strengths: string[];
  improvements: string[];
}

export default function InterviewArena() {
  const { refresh } = useAuth();
  const [stage, setStage] = useState<"pick" | "mcq" | "descriptive" | "done">("pick");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [mcqs, setMcqs] = useState<MCQ[]>([]);
  const [mcqIdx, setMcqIdx] = useState(0);
  const [mcqAnswers, setMcqAnswers] = useState<number[]>([]);
  const [timeLeft, setTimeLeft] = useState(SECS);
  const [mcqScore, setMcqScore] = useState<number | null>(null);
  const [question, setQuestion] = useState("");
  const [qNum, setQNum] = useState(0);
  const [total, setTotal] = useState(4);
  const [answer, setAnswer] = useState("");
  const [scores, setScores] = useState<Scores | null>(null);
  const [mcqReview, setMcqReview] = useState<McqReview[]>([]);
  const [transcript, setTranscript] = useState<{ q: string; a: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [customRole, setCustomRole] = useState("");
  const [jd, setJd] = useState("");
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number>(0);

  useEffect(() => () => window.clearInterval(timerRef.current), []);

  const start = async (role: string, jobDescription = "") => {
    setBusy(true);
    setScores(null);
    try {
      const res = await api<any>("/api/interview/start", { method: "POST", body: JSON.stringify({ role, job_description: jobDescription }) });
      setSessionId(res.session_id);
      setMcqs(res.questions);
      setMcqAnswers(new Array(res.questions.length).fill(-1));
      setMcqIdx(0);
      setStage("mcq");
      armTimer();
    } finally {
      setBusy(false);
    }
  };

  const armTimer = () => {
    window.clearInterval(timerRef.current);
    setTimeLeft(SECS);
    timerRef.current = window.setInterval(() => {
      setTimeLeft((t) => {
        if (t <= 1) {
          advance(-2); // timeout = unanswered
          return SECS;
        }
        return t - 1;
      });
    }, 1000);
  };

  const advance = (picked: number) => {
    setMcqAnswers((prev) => {
      const next = [...prev];
      setMcqIdx((idx) => {
        if (picked !== -2) next[idx] = picked;
        const nextIdx = idx + 1;
        if (nextIdx >= mcqs.length) {
          window.clearInterval(timerRef.current);
          submitMcq(next);
        } else {
          armTimer();
        }
        return Math.min(nextIdx, mcqs.length - 1);
      });
      return next;
    });
  };

  const submitMcq = async (answers: number[]) => {
    setBusy(true);
    try {
      const res = await api<any>("/api/interview/mcq", { method: "POST", body: JSON.stringify({ session_id: sessionId, answers }) });
      setMcqScore(res.mcq_score);
      setQuestion(res.question);
      setQNum(res.question_number);
      setTotal(res.total);
      setStage("descriptive");
    } finally {
      setBusy(false);
    }
  };

  const toggleMic = async () => {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const form = new FormData();
        form.append("file", new Blob(chunks, { type: "audio/webm" }), "answer.webm");
        try {
          const res = await fetch("/api/voice/transcribe", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: form });
          if (res.status === 501) {
            alert("Local STT not installed — pip install faster-whisper");
            return;
          }
          const { text } = await res.json();
          if (text) setAnswer((a) => (a ? a + " " : "") + text);
        } catch {
          /* keep typed text */
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      alert("Microphone permission denied.");
    }
  };

  const submitAnswer = async (finish = false) => {
    if (!answer.trim() || !sessionId) return;
    setBusy(true);
    try {
      const res = await api<any>("/api/interview/answer", { method: "POST", body: JSON.stringify({ session_id: sessionId, answer, finish }) });
      setAnswer("");
      if (res.finished) {
        setScores(res.scores);
        setMcqReview(res.mcq_review ?? []);
        setTranscript(res.transcript ?? []);
        setStage("done");
        refresh();
      } else {
        setQuestion(res.question);
        setQNum(res.question_number);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full max-w-none space-y-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-snow"><DecryptText text="Interview arena" /></h2>
        <p className="text-fog text-sm mt-1 font-mono">stage 1: rapid screen (10 MCQ, 30s each) · stage 2: deep dive (4 descriptive)</p>
      </div>

      {stage === "pick" && (
        <div className="card p-5">
          <p className="text-fog text-sm mb-4">Pick a track to begin the two-stage interview.</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {ROLES.map((r) => (
              <button key={r} className="bg-panel2 border border-line rounded-lg py-3 text-sm hover:border-brass transition-colors" onClick={() => start(r)} disabled={busy}>
                {r}
              </button>
            ))}
          </div>
          <div className="mt-5 pt-4 border-t border-line space-y-2">
            <p className="font-mono text-[10px] tracking-widest text-fog">OR TARGET A SPECIFIC JOB</p>
            <input className="input" placeholder="Job title, e.g. Senior GenAI Engineer — Fintech" value={customRole} onChange={(e) => setCustomRole(e.target.value)} />
            <textarea className="input min-h-24" placeholder="Paste the job description (optional) — every question gets tailored to it" value={jd} onChange={(e) => setJd(e.target.value)} />
            <button className="btn-brass" disabled={busy || (!customRole.trim() && !jd.trim())} onClick={() => start(customRole.trim() || "the role in this job description", jd)}>
              Start tailored interview
            </button>
          </div>
          {busy && <p className="text-fog text-sm mt-3 font-mono animate-pulse">Preparing your screening round…</p>}
        </div>
      )}

      {stage === "mcq" && mcqs[mcqIdx] && (
        <div className="card p-5 space-y-4">
          <div className="flex justify-between items-center">
            <span className="font-mono text-[10px] text-fog">RAPID SCREEN · Q{mcqIdx + 1}/{mcqs.length}</span>
            <span className={`font-mono text-sm ${timeLeft <= 10 ? "text-ember" : "text-brass"}`}>{timeLeft}s</span>
          </div>
          <div className="h-1 bg-panel2 rounded-full overflow-hidden">
            <div className="h-full bg-brass transition-all duration-1000" style={{ width: `${(timeLeft / SECS) * 100}%` }} />
          </div>
          <p className="text-sm text-snow leading-relaxed">{mcqs[mcqIdx].q}</p>
          <div className="space-y-2">
            {mcqs[mcqIdx].options.map((opt, i) => (
              <button key={i} onClick={() => advance(i)} className="w-full text-left text-xs px-3 py-2.5 rounded-lg border border-line bg-panel2 text-fog hover:border-brass/50 hover:text-snow transition-colors">
                <span className="font-mono text-brass mr-2">{String.fromCharCode(65 + i)}</span>
                {opt}
              </button>
            ))}
          </div>
        </div>
      )}

      {stage === "descriptive" && (
        <div className="card p-5 space-y-4">
          <div className="flex justify-between items-center">
            <span className="font-mono text-[10px] text-fog">DEEP DIVE · Q{qNum}/{total}</span>
            {mcqScore !== null && <span className="font-mono text-[10px] text-brass">SCREEN: {mcqScore}%</span>}
          </div>
          <p className="text-lg text-snow">{question}</p>
          <textarea className="input min-h-32" placeholder="Click the mic and answer out loud — or type…" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          <div className="flex gap-2">
            <button
              onClick={toggleMic}
              className={`rounded-lg border border-line px-3 py-2 transition-colors ${recording ? "bg-ember text-ink" : "bg-panel2 text-fog hover:text-brass"}`}
              title={recording ? "Stop and transcribe" : "Answer by voice"}
            >
              {recording ? <Square size={16} /> : <Mic size={16} />}
            </button>
            {qNum >= total ? (
              <>
                <button className="btn-brass flex-1" onClick={() => submitAnswer(true)} disabled={busy || recording}>
                  {busy ? "Evaluating…" : "Submit & get scorecard"}
                </button>
                <button
                  className="border border-brass/40 text-brass rounded-lg px-4 text-sm hover:bg-brass/10 transition-colors disabled:opacity-50"
                  onClick={() => submitAnswer(false)}
                  disabled={busy || recording}
                  title="Keep going — up to 10 questions total"
                >
                  Keep going
                </button>
              </>
            ) : (
              <button className="btn-brass flex-1" onClick={() => submitAnswer(false)} disabled={busy || recording}>
                {busy ? "Evaluating…" : "Submit answer"}
              </button>
            )}
          </div>
          {qNum > total && <p className="font-mono text-[10px] text-brass">EXTENDED ROUND · Q{qNum} of max 10</p>}
          {recording && <p className="font-mono text-[10px] text-ember animate-pulse">RECORDING — click the square when done, your words become the answer</p>}
        </div>
      )}

      {stage === "done" && scores && (
        <div className="card p-5 space-y-4">
          <div className="flex items-baseline justify-between">
            <h3 className="font-display text-lg text-snow">Scorecard</h3>
            <span className="font-mono text-xs text-brass">+200 XP · screen <AnimatedNumber value={scores.mcq_score ?? 0} />%</span>
          </div>
          <div className="space-y-2">
            {(["communication", "technical_accuracy", "confidence", "depth", "leadership"] as const).map((k) => (
              <div key={k} className="flex items-center gap-3 text-sm">
                <span className="w-44 text-fog capitalize text-xs">{k.replace(/_/g, " ")}{k === "technical_accuracy" && <span className="font-mono text-[8px] text-brass ml-1">MCQ-blended</span>}</span>
                <div className="flex-1 h-1.5 bg-panel2 rounded-full overflow-hidden">
                  <div className="h-full bg-brass rounded-full" style={{ width: `${(scores[k] ?? 0) * 10}%` }} />
                </div>
                <span className="font-mono text-xs w-9 text-right">{scores[k]}/10</span>
              </div>
            ))}
          </div>
          <p className="text-sm text-fog">{scores.feedback}</p>
          <div className="grid sm:grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-sage font-medium mb-1 text-xs font-mono uppercase tracking-wider">Strengths</p>
              <ul className="text-fog space-y-1 text-xs">{scores.strengths?.map((s, i) => <li key={i}>· {s}</li>)}</ul>
            </div>
            <div>
              <p className="text-ember font-medium mb-1 text-xs font-mono uppercase tracking-wider">Improve next</p>
              <ul className="text-fog space-y-1 text-xs">{scores.improvements?.map((s, i) => <li key={i}>· {s}</li>)}</ul>
            </div>
          </div>
          <details className="border border-line rounded-lg p-3">
            <summary className="font-mono text-[10px] tracking-widest text-fog cursor-pointer">RAPID SCREEN REVIEW — YOUR ANSWERS</summary>
            <div className="space-y-2 mt-3">
              {mcqReview.map((r, i) => (
                <div key={i} className={`text-xs px-3 py-2 rounded-lg border ${r.ok ? "border-sage/30" : "border-ember/40 bg-panel2"}`}>
                  <p className="text-snow">
                    <span className={`font-mono mr-2 ${r.ok ? "text-sage" : "text-ember"}`}>{r.ok ? "✓" : "✗"}</span>
                    {r.q}
                  </p>
                  <p className="font-mono text-[10px] text-fog mt-1">
                    you: {r.given >= 0 ? `${String.fromCharCode(65 + r.given)} — ${r.options[r.given]}` : "no answer (timed out)"}
                    {!r.ok && <span className="text-sage"> · correct: {String.fromCharCode(65 + r.correct)} — {r.options[r.correct]}</span>}
                  </p>
                </div>
              ))}
            </div>
          </details>
          <details className="border border-line rounded-lg p-3">
            <summary className="font-mono text-[10px] tracking-widest text-fog cursor-pointer">DEEP DIVE TRANSCRIPT — YOUR ANSWERS</summary>
            <div className="space-y-3 mt-3">
              {transcript.map((t, i) => (
                <div key={i} className="text-xs">
                  <p className="text-brass font-mono mb-1">Q{i + 1}: {t.q}</p>
                  <p className="text-fog leading-relaxed">{t.a || "—"}</p>
                </div>
              ))}
            </div>
          </details>
          <button className="btn-brass w-full" onClick={() => setStage("pick")}>New interview</button>
        </div>
      )}
    </div>
  );
}
