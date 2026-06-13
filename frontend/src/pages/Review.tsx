import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { AnimatedNumber, DecryptText } from "../lib/fx";
import { unlock } from "../lib/sound";
import { useAuth } from "../store/auth";

interface DueItem {
  id: number;
  node_title: string;
  due_at: string;
  is_due: boolean;
  interval_stage: number;
  strength: number;
}
interface Q { q: string; options: string[]; answer: number; }

export default function Review() {
  const { refresh } = useAuth();
  const [items, setItems] = useState<DueItem[]>([]);
  const [strength, setStrength] = useState(1);
  const [dueCount, setDueCount] = useState(0);
  const [active, setActive] = useState<{ id: number; title: string; qs: Q[] } | null>(null);
  const [answers, setAnswers] = useState<number[]>([]);
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<{ passed: boolean; score: number; next_due: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    api<{ items: DueItem[]; memory_strength: number; reviews_due: number }>("/api/review/due").then((r) => {
      setItems(r.items);
      setStrength(r.memory_strength);
      setDueCount(r.reviews_due);
    }).catch(() => {});
  useEffect(() => { load(); }, []);

  const start = async (it: DueItem) => {
    setBusy(true);
    try {
      const r = await api<{ review_id: number; node_title: string; questions: Q[] }>(`/api/review/${it.id}/start`, { method: "POST" });
      setActive({ id: r.review_id, title: r.node_title, qs: r.questions });
      setAnswers(new Array(r.questions.length).fill(-1));
      setIdx(0);
      setResult(null);
    } finally { setBusy(false); }
  };

  const pick = (o: number) => {
    const next = [...answers]; next[idx] = o; setAnswers(next);
    if (idx < active!.qs.length - 1) setIdx(idx + 1);
  };

  const submit = async () => {
    if (!active) return;
    const correct = active.qs.reduce((acc, q, i) => acc + (answers[i] === q.answer ? 1 : 0), 0);
    const score = Math.round((100 * correct) / active.qs.length);
    setBusy(true);
    try {
      const r = await api<{ passed: boolean; score: number; next_due: string }>(`/api/review/${active.id}/submit`, {
        method: "POST", body: JSON.stringify({ score }),
      });
      setResult(r);
      if (r.passed) unlock();
      refresh(); load();
    } finally { setBusy(false); }
  };

  const strengthColor = (s: number) => (s > 0.7 ? "#7FB58C" : s > 0.4 ? "#D4B36A" : "#D98A6A");

  if (active && !result) {
    const q = active.qs[idx];
    const answered = answers.filter((a) => a >= 0).length;
    return (
      <div className="w-full max-w-2xl mx-auto space-y-5">
        <p className="font-mono text-[10px] tracking-widest text-cyan">RECALL · {active.title}</p>
        <div className="card p-5 space-y-4">
          <div className="flex justify-between font-mono text-[10px] text-fog">
            <span>Q{idx + 1} / {active.qs.length}</span>
            <button onClick={() => setActive(null)} className="hover:text-snow">exit</button>
          </div>
          <div className="h-1 bg-panel2 rounded-full overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${(answered / active.qs.length) * 100}%`, background: "linear-gradient(90deg,#D4B36A,#5FD3E0)" }} />
          </div>
          <p className="text-sm text-snow leading-relaxed">{q.q}</p>
          <div className="space-y-2">
            {q.options.map((o, i) => (
              <button key={i} onClick={() => pick(i)} className={`w-full text-left text-xs px-3 py-2.5 rounded-lg border transition-colors ${answers[idx] === i ? "border-cyan bg-cyan/10 text-snow" : "border-line bg-panel2 text-fog hover:border-cyan/40 hover:text-snow"}`}>
                <span className="font-mono text-cyan mr-2">{String.fromCharCode(65 + i)}</span>{o}
              </button>
            ))}
          </div>
          <button className="btn-brass w-full" disabled={answered < active.qs.length || busy} onClick={submit}>
            {busy ? "Grading…" : `Submit recall (${answered}/${active.qs.length})`}
          </button>
        </div>
      </div>
    );
  }

  if (result) {
    return (
      <div className="w-full max-w-2xl mx-auto">
        <div className="card p-6 text-center space-y-3">
          <p className="font-mono text-[10px] tracking-[0.3em] text-fog">RECALL RESULT</p>
          <p className="font-display text-5xl" style={{ color: result.passed ? "#5FD3E0" : "#D98A6A" }}>
            <AnimatedNumber value={result.score} />%
          </p>
          <p className="font-mono text-xs text-fog">
            {result.passed ? `memory reinforced · next review ${result.next_due}` : `interval reset · review again ${result.next_due}`}
          </p>
          <button className="btn-brass" onClick={() => { setActive(null); setResult(null); }}>Done</button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-none space-y-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-snow"><DecryptText text="Review queue" /></h2>
        <p className="text-fog text-sm mt-1 font-mono">spaced repetition fights forgetting · review before knowledge decays</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div className="card p-4">
          <p className="font-mono text-[10px] text-fog tracking-widest">DUE NOW</p>
          <p className="font-display text-3xl mt-1" style={{ color: dueCount > 0 ? "#5FD3E0" : "#7FB58C" }}><AnimatedNumber value={dueCount} /></p>
        </div>
        <div className="card p-4">
          <p className="font-mono text-[10px] text-fog tracking-widest">MEMORY STRENGTH</p>
          <p className="font-display text-3xl mt-1" style={{ color: strengthColor(strength) }}>{Math.round(strength * 100)}%</p>
        </div>
        <div className="card p-4">
          <p className="font-mono text-[10px] text-fog tracking-widest">TRACKED</p>
          <p className="font-display text-3xl mt-1 text-snow"><AnimatedNumber value={items.length} /></p>
        </div>
      </div>

      {items.length === 0 && (
        <div className="card p-6 text-center">
          <p className="text-fog text-sm">No topics tracked yet. Complete a roadmap node's assessment and it enters the review cycle automatically.</p>
        </div>
      )}

      <div className="space-y-2">
        {items.map((it) => (
          <div key={it.id} className="card p-4 flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-snow truncate">{it.node_title}</p>
              <div className="flex items-center gap-3 mt-2">
                <div className="h-1.5 w-28 bg-panel2 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${it.strength * 100}%`, background: strengthColor(it.strength) }} />
                </div>
                <span className="font-mono text-[10px] text-fog">stage {it.interval_stage} · {it.is_due ? "due now" : `due ${it.due_at}`}</span>
              </div>
            </div>
            <button className={it.is_due ? "btn-brass text-sm shrink-0" : "btn-cyan text-sm shrink-0"} disabled={busy} onClick={() => start(it)}>
              {it.is_due ? "Review" : "Review early"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
