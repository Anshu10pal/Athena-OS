import { useOrb } from "../store/orb";

export default function HudTelemetry() {
  const { state, metrics } = useOrb();
  return (
    <div
      className="fixed bottom-3 right-4 font-mono text-[10px] text-fog flex items-center gap-4 bg-panel/80 border border-line rounded-md px-3 py-1.5 backdrop-blur-sm"
      style={{ zIndex: 30 }}
    >
      <span>
        STATE <span className="text-brass uppercase">{state}</span>
      </span>
      {metrics.intent && (
        <span>
          AGENT <span className="text-brass uppercase">{metrics.intent}</span>
        </span>
      )}
      {metrics.latencyMs !== undefined && (
        <span>
          TTFB <span className="text-snow">{metrics.latencyMs}ms</span>
        </span>
      )}
      {metrics.tps !== undefined && (
        <span>
          <span className="text-snow">{metrics.tps}</span> tok/s
        </span>
      )}
    </div>
  );
}
