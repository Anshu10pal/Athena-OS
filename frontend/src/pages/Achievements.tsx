import { useEffect, useState } from "react";
import { DecryptText } from "../lib/fx";
import { api } from "../lib/api";

interface Badge {
  code: string; title: string; description: string; icon: string; tier: string;
  unlocked: boolean; unlocked_at: string | null;
}
const TIER: Record<string, string> = { bronze: "#C77B4A", silver: "#94A3B8", gold: "#22C55E" };

export default function Achievements() {
  const [badges, setBadges] = useState<Badge[]>([]);
  const [count, setCount] = useState(0);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    api<{ achievements: Badge[]; unlocked_count: number; total: number }>("/api/achievements").then((r) => {
      setBadges(r.achievements); setCount(r.unlocked_count); setTotal(r.total);
    }).catch(() => {});
  }, []);

  return (
    <div className="w-full max-w-none space-y-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-snow"><DecryptText text="Achievements" /></h2>
        <p className="text-fog text-sm mt-1 font-mono">{count} of {total} unlocked</p>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {badges.map((b) => (
          <div key={b.code} className="card p-4 text-center" style={{ opacity: b.unlocked ? 1 : 0.4 }}>
            <div className="mx-auto w-14 h-14 rounded-full grid place-items-center mb-3" style={{
              border: `1.5px solid ${b.unlocked ? TIER[b.tier] : "#475569"}`,
              background: b.unlocked ? `${TIER[b.tier]}1a` : "transparent",
            }}>
              <span style={{ fontSize: 22, filter: b.unlocked ? "none" : "grayscale(1)" }}>{b.unlocked ? "★" : "🔒"}</span>
            </div>
            <p className="text-sm font-medium text-snow">{b.title}</p>
            <p className="text-fog text-[11px] mt-1 leading-snug">{b.description}</p>
            {b.unlocked && b.unlocked_at && <p className="font-mono text-[9px] mt-2" style={{ color: TIER[b.tier] }}>{b.unlocked_at}</p>}
            {b.unlocked && <p className="font-mono text-[8px] mt-1 uppercase tracking-widest text-fog">{b.tier}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
