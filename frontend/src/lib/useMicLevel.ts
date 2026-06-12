import { useRef } from "react";
import { useOrb } from "../store/orb";

/** Feeds live audio amplitude (0..1) from a MediaStream or HTMLAudioElement into orb.audioLevel. */
export function useAudioReactive() {
  const { audioLevel } = useOrb();
  const cleanup = useRef<(() => void) | null>(null);

  const attach = (source: MediaStream | HTMLAudioElement) => {
    detach();
    const actx = new AudioContext();
    const analyser = actx.createAnalyser();
    analyser.fftSize = 256;
    let srcNode: AudioNode;
    if (source instanceof MediaStream) {
      srcNode = actx.createMediaStreamSource(source);
      srcNode.connect(analyser);
    } else {
      srcNode = actx.createMediaElementSource(source);
      srcNode.connect(analyser);
      analyser.connect(actx.destination);
    }
    const data = new Uint8Array(analyser.frequencyBinCount);
    let raf = 0;
    const loop = () => {
      analyser.getByteFrequencyData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i];
      audioLevel.current = Math.min(1, (sum / data.length / 255) * 2.5);
      raf = requestAnimationFrame(loop);
    };
    loop();
    cleanup.current = () => {
      cancelAnimationFrame(raf);
      audioLevel.current = 0;
      actx.close().catch(() => {});
    };
  };

  const detach = () => {
    cleanup.current?.();
    cleanup.current = null;
  };

  return { attach, detach };
}
