import { createContext, useContext, useRef, useState, type MutableRefObject, type ReactNode } from "react";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

export interface Metrics {
  intent?: string;
  latencyMs?: number;
  tps?: number;
}

interface OrbCtx {
  state: OrbState;
  setState: (s: OrbState) => void;
  audioLevel: MutableRefObject<number>;
  metrics: Metrics;
  setMetrics: (m: Metrics) => void;
  notifyXp: (newXp: number, gained: number) => void;
}

const Ctx = createContext<OrbCtx | null>(null);

export function OrbProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<OrbState>("idle");
  const [metrics, setMetrics] = useState<Metrics>({});
  const audioLevel = useRef(0);

  const notifyXp = (newXp: number, gained: number) => {
    if (!gained) return;
    const oldXp = newXp - gained;
    const oldLevel = Math.floor(oldXp / 500);
    const newLevel = Math.floor(newXp / 500);
    if (newLevel > oldLevel) {
      window.dispatchEvent(new CustomEvent("athena:levelup", { detail: { level: newLevel + 1 } }));
    }
  };

  return (
    <Ctx.Provider value={{ state, setState, audioLevel, metrics, setMetrics, notifyXp }}>{children}</Ctx.Provider>
  );
}

export function useOrb(): OrbCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useOrb must be used inside OrbProvider");
  return ctx;
}
