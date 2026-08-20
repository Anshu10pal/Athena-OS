import { useEffect, useState } from "react";
import { api } from "../lib/api";

// The first user surface for comprehension cards.
//
// Phase 5 generated 661 of them and shipped no way to see one; they were
// reachable only through the API. This panel is deliberately the SMALLEST thing
// that makes them usable, and three boundaries are decisions rather than
// omissions:
//
//   * It is a practice panel, NOT spaced repetition. Cards are practised
//     per-module, on demand. Scheduling and cross-module due-card queues are a
//     separate piece of work and nothing here touches them.
//   * It is STATELESS. Nothing is persisted -- no attempt rows, no
//     ModuleAssessment. That wiring is the next checkpoint, kept separate so
//     this viewer is verified before persistence can confuse its diagnosis.
//   * Score is RECALLED, not graded. "4 of 6 recalled", never a percentage, an
//     XP award, or a pass mark. These cards test recall of structure -- which
//     file imports which -- and a UI implying comprehension would claim more
//     than the deterministic tier delivers.
//
// Grading is a round trip to POST /repos/{id}/cards/{cardId}/grade rather than
// a string comparison here. `grade_deterministic_card` normalises with
// `" ".join(text.split()).casefold()`; a local match would agree with it until
// someone changed that normalisation, and then a card the backend calls correct
// would read wrong in the browser with nothing failing. One rule, one home
// (§17.28).

export interface CardT {
  id: number;
  module_id: number;
  template: string;
  card_source: string;
  question: string;
  options: string[];
  answer: string;
  rationale: string;
  subject_path: string | null;
}

interface GradeT {
  card_id: number;
  correct: boolean;
  rationale: string;
  answer: string;
}

/** Renders `code` spans for text the generator wrapped in backticks. The
 *  questions name real paths and reading them as prose is harder than it needs
 *  to be. */
function withCode(text: string) {
  return text.split(/(`[^`]+`)/g).map((part, i) =>
    part.startsWith("`") && part.endsWith("`") ? (
      <code key={i} className="font-mono text-[11px] text-accent">{part.slice(1, -1)}</code>
    ) : (
      <span key={i}>{part}</span>
    ));
}

export function CardPractice({ repoId, moduleId }: { repoId: number; moduleId: number }) {
  const [cards, setCards] = useState<CardT[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [grade, setGrade] = useState<GradeT | null>(null);
  const [grading, setGrading] = useState(false);
  const [recalled, setRecalled] = useState(0);
  const [answered, setAnswered] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<{ cards: CardT[] }>(`/api/repos/${repoId}/cards?module_id=${moduleId}&limit=50`)
      .then((r) => { if (!cancelled) setCards(r.cards); })
      .catch(() => { if (!cancelled) setError("Could not load practice cards."); });
    return () => { cancelled = true; };
  }, [repoId, moduleId]);

  // Loading and empty are DIFFERENT states and must not render alike. An empty
  // panel and a not-yet-loaded panel look identical to a careless reader (and
  // to a careless probe), which is the whole reason this is spelled out.
  if (error) {
    return <p className="font-mono text-[10px] text-danger" data-testid="cards-error">{error}</p>;
  }
  if (cards === null) {
    return <p className="font-mono text-[10px] text-fog" data-testid="cards-loading">Loading practice cards…</p>;
  }

  // 24 of Superset's 122 modules produce no cards at all: the deterministic
  // templates need import edges, fan-in or layer depth, and a module with none
  // offers nothing to ask about. Saying so is the same honesty rule the graph's
  // truncation notice follows -- an empty box would read as a broken panel.
  if (cards.length === 0) {
    return (
      <div className="card p-4" data-testid="cards-empty">
        <h3 className="font-mono text-[10px] uppercase tracking-widest text-fog">Check your recall</h3>
        <p className="mt-2 text-sm text-fog">
          No practice cards for this module. The questions are generated from import
          edges, fan-in and layer depth, and this module has none of that structure to
          ask about — so there is nothing to test rather than nothing to show.
        </p>
      </div>
    );
  }

  const card = cards[index];
  const source = cards[0].card_source;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="cards-open"
        className="card p-4 w-full text-left hover:border-accent/40 transition-colors"
      >
        <h3 className="font-mono text-[10px] uppercase tracking-widest text-fog">Check your recall</h3>
        <p className="mt-1.5 font-mono text-[11px] text-snow">
          {cards.length} card{cards.length === 1 ? "" : "s"} · {source}
        </p>
      </button>
    );
  }

  const submit = async (option: string) => {
    if (grade || grading) return;
    setPicked(option);
    setGrading(true);
    try {
      const g = await api<GradeT>(`/api/repos/${repoId}/cards/${card.id}/grade`, {
        method: "POST",
        body: JSON.stringify({ response: option }),
      });
      setGrade(g);
      setAnswered((n) => n + 1);
      if (g.correct) setRecalled((n) => n + 1);
    } catch {
      setError("Could not grade that answer.");
    } finally {
      setGrading(false);
    }
  };

  const next = () => {
    setPicked(null);
    setGrade(null);
    setIndex((i) => i + 1);
  };

  const done = index >= cards.length;

  return (
    <div className="card p-4 space-y-3" data-testid="cards-panel">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-mono text-[10px] uppercase tracking-widest text-fog">Check your recall</h3>
        <span className="font-mono text-[10px] text-fog" data-testid="cards-progress">
          {recalled} of {answered || cards.length} recalled
        </span>
      </div>

      {done ? (
        <div data-testid="cards-finished">
          <p className="text-sm text-snow">
            {recalled} of {answered} recalled.
          </p>
          <p className="mt-1 text-xs text-fog">
            Nothing is saved — this is practice, not a test.
          </p>
          <button
            type="button"
            className="mt-2 font-mono text-[10px] uppercase tracking-widest text-accent"
            onClick={() => { setIndex(0); setRecalled(0); setAnswered(0); setPicked(null); setGrade(null); }}
          >
            Run again
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[9px] uppercase tracking-widest text-fog/70"
                  data-testid="card-source">{card.card_source}</span>
            <span className="font-mono text-[9px] text-fog/70">card {index + 1} of {cards.length}</span>
          </div>

          <p className="text-sm text-snow" data-testid="card-question">{withCode(card.question)}</p>

          <div className="space-y-1.5">
            {card.options.map((o) => {
              const isAnswer = grade && o === grade.answer;
              const isPickedWrong = grade && o === picked && !grade.correct;
              return (
                <button
                  key={o}
                  type="button"
                  disabled={!!grade || grading}
                  onClick={() => submit(o)}
                  data-testid="card-option"
                  className={
                    "w-full text-left font-mono text-[11px] rounded border px-2.5 py-1.5 transition-colors " +
                    (isAnswer
                      ? "border-accent text-accent"
                      : isPickedWrong
                        ? "border-danger text-danger"
                        : "border-line text-fog hover:text-snow")
                  }
                >
                  {o}
                </button>
              );
            })}
          </div>

          {grade && (
            // The rationale is the point of getting one wrong: it names the
            // stored fact the answer came from, so a miss teaches the edge
            // rather than only marking the attempt.
            <div data-testid="card-rationale" className="space-y-1">
              <p className={"font-mono text-[10px] uppercase tracking-widest " +
                (grade.correct ? "text-accent" : "text-danger")}>
                {grade.correct ? "recalled" : "not recalled"}
              </p>
              <p className="text-xs text-fog">{withCode(grade.rationale)}</p>
              {card.subject_path && (
                <p className="font-mono text-[10px] text-fog/70">{card.subject_path}</p>
              )}
              <button
                type="button"
                onClick={next}
                data-testid="card-next"
                className="mt-1 font-mono text-[10px] uppercase tracking-widest text-accent"
              >
                {index + 1 === cards.length ? "Finish" : "Next card"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
