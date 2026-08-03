import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { AnimatedNumber } from "../lib/fx";
import { chime, unlock } from "../lib/sound";
import { useOrb } from "../store/orb";

interface Q {
  q: string;
  options: string[];
  topic: string;
}

interface Result {
  score: number;
  passed: boolean;
  xp: number;
  xp_gained: number;
  results: { q: string; given: number; correct: number; ok: boolean; topic: string }[];
  weak_topics: string[];
  nodes: any[] | null;
}

export default function AssessmentRunner({
  roadmapId,
  nodeId,
  onDone,
  onBack,
}: {
  roadmapId: number;
  nodeId: string;
  onDone: (nodes: any[] | null, xp: number, gained: number) => void;
  onBack: () => void;
}) {
  const { notifyXp } = useOrb();
  const [assessmentId, setAssessmentId] = useState<number | null>(null);
  const [questions, setQuestions] = useState<Q[]>([]);
  const [answers, setAnswers] = useState<number[]>([]);
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ assessment_id: number; questions: Q[] }>(`/api/roadmap/${roadmapId}/node/${nodeId}/assessment/start`, { method: "POST" })
      .then((r) => {
        setAssessmentId(r.assessment_id);
        setQuestions(r.questions);
      })
      .catch((e) => setError(e.message));
  }, [roadmapId, nodeId]);

  const pick = (opt: number) => {
    const next = [...answers];
    next[idx] = opt;
    setAnswers(next);
    if (idx < questions.length - 1) setIdx(idx + 1);
  };

  const submit = async () => {
    if (!assessmentId) return;
    setBusy(true);
    try {
      const r = await api<Result>(`/api/roadmap/assessment/${assessmentId}/submit`, {
        method: "POST",
        body: JSON.stringify({ answers }),
      });
      setResult(r);
      if (r.passed) {
        unlock();
        notifyXp(r.xp, r.xp_gained);
      } else {
        chime();
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (error)
    return (
      <div className="flex-1 p-5">
        <p className="text-danger text-sm">{error}</p>
        <button onClick={onBack} className="text-fog text-xs mt-3 hover:text-snow font-mono">← back to dossier</button>
      </div>
    );

  if (result)
    return (
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        <div className="text-center py-4">
          <p className="font-mono text-[10px] tracking-[0.3em] text-fog">ASSESSMENT RESULT</p>
          <p className={`font-display text-5xl mt-2 ${result.passed ? "text-accent" : "text-danger"}`}>
            <AnimatedNumber value={result.score} />%
          </p>
          <p className="font-mono text-xs mt-2 text-fog">
            {result.passed ? `PASSED — node completed · +${result.xp_gained} XP` : "BELOW 70% — review and retry"}
          </p>
        </div>
        {result.weak_topics.length > 0 && (
          <div className="card p-3">
            <p className="font-mono text-[10px] tracking-widest text-fog mb-1.5">REVIEW THESE AREAS</p>
            <p className="text-xs text-snow">{result.weak_topics.join(" · ")}</p>
          </div>
        )}
        <div className="space-y-1.5">
          {result.results.map((r, i) => (
            <div key={i} className={`text-xs px-3 py-2 rounded-lg border ${r.ok ? "border-accent/30 text-fog" : "border-danger/40 text-snow bg-panel2"}`}>
              <span className={`font-mono mr-2 ${r.ok ? "text-accent" : "text-danger"}`}>{r.ok ? "✓" : "✗"}</span>
              {r.q}
            </div>
          ))}
        </div>
        <button
          className="btn-accent w-full"
          onClick={() => onDone(result.nodes, result.xp, result.xp_gained)}
        >
          {result.passed ? "Continue" : "Back to study material"}
        </button>
      </div>
    );

  if (!questions.length)
    return <div className="flex-1 p-5"><p className="text-fog text-sm font-mono animate-pulse">Generating your assessment…</p></div>;

  const q = questions[idx];
  const answered = answers.filter((a) => a !== undefined).length;

  return (
    <div className="flex-1 flex flex-col p-5">
      <div className="flex justify-between items-center mb-3">
        <span className="font-mono text-[10px] text-fog">
          Q{idx + 1} / {questions.length} · {q.topic}
        </span>
        <button onClick={onBack} className="font-mono text-[10px] text-fog hover:text-snow">exit</button>
      </div>
      <div className="h-1 bg-panel2 rounded-full mb-4 overflow-hidden">
        <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${(answered / questions.length) * 100}%` }} />
      </div>
      <p className="text-sm text-snow leading-relaxed mb-4">{q.q}</p>
      <div className="space-y-2">
        {q.options.map((opt, i) => (
          <button
            key={i}
            onClick={() => pick(i)}
            className={`w-full text-left text-xs px-3 py-2.5 rounded-lg border transition-colors ${
              answers[idx] === i ? "border-accent bg-accent/10 text-snow" : "border-line bg-panel2 text-fog hover:border-accent/40 hover:text-snow"
            }`}
          >
            <span className="font-mono text-accent mr-2">{String.fromCharCode(65 + i)}</span>
            {opt}
          </button>
        ))}
      </div>
      <div className="mt-auto pt-4 flex gap-2">
        <button disabled={idx === 0} onClick={() => setIdx(idx - 1)} className="text-fog text-xs font-mono disabled:opacity-30 hover:text-snow">
          ← prev
        </button>
        <button disabled={idx >= questions.length - 1} onClick={() => setIdx(idx + 1)} className="text-fog text-xs font-mono disabled:opacity-30 hover:text-snow">
          next →
        </button>
        <button className="btn-accent ml-auto text-sm" disabled={answered < questions.length || busy} onClick={submit}>
          {busy ? "Grading…" : `Submit (${answered}/${questions.length})`}
        </button>
      </div>
    </div>
  );
}
