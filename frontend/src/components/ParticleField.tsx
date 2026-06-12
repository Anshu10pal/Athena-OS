import { useEffect, useRef } from "react";
import { useOrb } from "../store/orb";

/** Brass plexus particle field. Reacts to Athena's state:
 * idle=drift, listening=gravitate to center, thinking=orbit, speaking=radiate. */
export default function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const orb = useOrb();
  const stateRef = useRef(orb.state);
  stateRef.current = orb.state;

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let W = 0;
    let H = 0;
    const resize = () => {
      W = canvas.width = window.innerWidth;
      H = canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    const N = 80;
    const ps = Array.from({ length: N }, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
    }));

    let raf = 0;
    const tick = () => {
      ctx.clearRect(0, 0, W, H);
      const cx = W / 2;
      const cy = H / 2;
      const mode = stateRef.current;
      const boost = orb.audioLevel.current;

      for (const p of ps) {
        if (mode === "listening") {
          p.vx += (cx - p.x) * 0.00008;
          p.vy += (cy - p.y) * 0.00008;
        } else if (mode === "thinking") {
          const dx = p.x - cx;
          const dy = p.y - cy;
          p.vx += -dy * 0.00012;
          p.vy += dx * 0.00012;
        } else if (mode === "speaking") {
          const dx = p.x - cx;
          const dy = p.y - cy;
          const d = Math.hypot(dx, dy) || 1;
          p.vx += (dx / d) * (0.008 + boost * 0.04);
          p.vy += (dy / d) * (0.008 + boost * 0.04);
        }
        p.vx *= 0.985;
        p.vy *= 0.985;
        p.x += p.vx + (mode === "idle" ? 0.12 : 0);
        p.y += p.vy;
        if (p.x < 0) p.x = W;
        if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H;
        if (p.y > H) p.y = 0;
      }
      for (let i = 0; i < N; i++)
        for (let j = i + 1; j < N; j++) {
          const a = ps[i];
          const b = ps[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < 100) {
            ctx.strokeStyle = `rgba(212,179,106,${(1 - d / 100) * 0.16})`;
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      ctx.fillStyle = "rgba(212,179,106,0.55)";
      for (const p of ps) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.2 + boost * 1.5, 0, 7);
        ctx.fill();
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="fixed inset-0 pointer-events-none" style={{ zIndex: 0 }} />;
}
