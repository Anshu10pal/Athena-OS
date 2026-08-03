/** Segmented arc gauge for 0-100 metrics. */
export default function ArcGauge({ value, label, size = 76 }: { value: number; label: string; size?: number }) {
  const r = 30;
  const circumference = Math.PI * r * 1.5;
  const filled = (Math.min(100, Math.max(0, value)) / 100) * circumference;
  return (
    <div className="flex flex-col items-center gap-1" title={`${label}: ${value}`}>
      <svg width={size} height={size * 0.78} viewBox="0 0 80 62" role="img" aria-label={`${label} ${value} out of 100`}>
        <path d="M 11.7 56.7 A 30 30 0 1 1 68.3 56.7" fill="none" stroke="#475569" strokeWidth="5" strokeLinecap="round" />
        <path
          d="M 11.7 56.7 A 30 30 0 1 1 68.3 56.7"
          fill="none"
          stroke="#22C55E"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          style={{ transition: "stroke-dasharray 0.8s ease-out" }}
        />
        <text x="40" y="44" textAnchor="middle" fontSize="16" fill="#F8FAFC" fontFamily="'Fira Code', monospace">
          {value}
        </text>
      </svg>
      <span className="text-[9px] font-mono uppercase tracking-wider text-fog">{label}</span>
    </div>
  );
}
