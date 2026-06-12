import { Upload } from "lucide-react";
import { useState } from "react";
import { getToken } from "../lib/api";

interface Analysis {
  overall_score: number;
  storytelling: string;
  business_impact: string;
  technical_depth: string;
  slide_feedback: { slide: number; feedback: string }[];
  executive_summary: string;
  speaker_notes: { slide: number; notes: string }[];
}

export default function PresentationArena() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Analysis | null>(null);
  const [error, setError] = useState("");

  const upload = async (file: File) => {
    setBusy(true);
    setError("");
    setResult(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/presentation/analyze", {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: form,
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Analysis failed");
      setResult(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full max-w-none space-y-6">
      <h2 className="font-display text-2xl font-semibold">Presentation Arena</h2>
      <label className="card p-10 flex flex-col items-center gap-3 cursor-pointer hover:border-brass transition-colors">
        <Upload className="text-brass" />
        <p className="text-sm">{busy ? "Athena is reviewing your deck…" : "Upload a .pptx or .pdf deck"}</p>
        <p className="text-xs text-fog">Slide feedback, storytelling review, speaker notes, executive summary</p>
        <input
          type="file"
          accept=".pptx,.pdf"
          className="hidden"
          disabled={busy}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
      </label>
      {error && <p className="text-ember text-sm">{error}</p>}

      {result && (
        <div className="space-y-4">
          <div className="card p-5">
            <p className="font-display text-lg">
              Overall: <span className="text-brass font-mono">{result.overall_score}/10</span>
            </p>
            <p className="text-sm text-fog mt-2">{result.executive_summary}</p>
          </div>
          <div className="grid sm:grid-cols-3 gap-4">
            {(["storytelling", "business_impact", "technical_depth"] as const).map((k) => (
              <div key={k} className="card p-4">
                <p className="text-xs uppercase tracking-wider text-fog mb-1">{k.replace(/_/g, " ")}</p>
                <p className="text-sm">{result[k]}</p>
              </div>
            ))}
          </div>
          <div className="card p-5">
            <h3 className="font-display mb-3">Slide-by-slide</h3>
            <ul className="space-y-2 text-sm">
              {result.slide_feedback?.map((s) => (
                <li key={s.slide} className="flex gap-3">
                  <span className="font-mono text-brass shrink-0">S{s.slide}</span>
                  <span className="text-fog">{s.feedback}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card p-5">
            <h3 className="font-display mb-3">Speaker notes</h3>
            <ul className="space-y-2 text-sm">
              {result.speaker_notes?.map((s) => (
                <li key={s.slide} className="flex gap-3">
                  <span className="font-mono text-brass shrink-0">S{s.slide}</span>
                  <span className="text-fog">{s.notes}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
