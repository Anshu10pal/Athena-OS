import { useEffect, useRef } from "react";

/**
 * Browser wake-word listener. Uses webkitSpeechRecognition (Chrome/Edge).
 * Fires onWake() when it hears "athena". Calls onReady(true) once actively listening.
 * Controlled by the localStorage flag "athena_wakeword". No-op on unsupported browsers.
 */
export function useWakeWord(onWake: () => void, onReady?: (ready: boolean) => void) {
  const cbRef = useRef(onWake);
  cbRef.current = onWake;
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    if (localStorage.getItem("athena_wakeword") !== "1") return;
    const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SR) {
      console.warn("[wake word] SpeechRecognition not supported in this browser (use Chrome/Edge).");
      return;
    }

    let stopped = false;
    let restartTimer: any;
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";

    rec.onstart = () => readyRef.current?.(true);
    rec.onresult = (e: any) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i][0].transcript.toLowerCase().includes("athena")) {
          cbRef.current();
          break;
        }
      }
    };
    rec.onerror = (e: any) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        console.warn("[wake word] microphone permission denied.");
        readyRef.current?.(false);
        stopped = true; // don't loop on a permission denial
      }
    };
    rec.onend = () => {
      readyRef.current?.(false);
      if (!stopped) restartTimer = setTimeout(() => { try { rec.start(); } catch {} }, 400);
    };

    try { rec.start(); } catch {}
    return () => {
      stopped = true;
      clearTimeout(restartTimer);
      try { rec.stop(); } catch {}
    };
  }, []);
}
