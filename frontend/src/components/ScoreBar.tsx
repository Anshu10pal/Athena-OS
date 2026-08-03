const TONES = {
  accent: "bg-accent",
  info: "bg-info",
  warning: "bg-warning",
  danger: "bg-danger",
};

/** Labeled horizontal progress fill for scores/stats (0-100). */
export default function ScoreBar({
  label,
  value,
  tone = "accent",
  valueLabel,
}: {
  label: string;
  value: number;
  tone?: keyof typeof TONES;
  valueLabel?: string;
}) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-fog mb-1">
        <span>{label}</span>
        <span className="font-mono">{valueLabel ?? `${Math.round(pct)}%`}</span>
      </div>
      <div className="h-1.5 bg-panel2 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${TONES[tone]}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
