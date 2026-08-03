let ctx: AudioContext | null = null;
let muted = localStorage.getItem("athena_muted") === "1";

function ac(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

export const isMuted = () => muted;
export function toggleMute(): boolean {
  muted = !muted;
  localStorage.setItem("athena_muted", muted ? "1" : "0");
  return muted;
}

function blip(freq: number, t0: number, dur: number, vol = 0.06) {
  const a = ac();
  const osc = a.createOscillator();
  const gain = a.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, a.currentTime + t0);
  gain.gain.linearRampToValueAtTime(vol, a.currentTime + t0 + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, a.currentTime + t0 + dur);
  osc.connect(gain).connect(a.destination);
  osc.start(a.currentTime + t0);
  osc.stop(a.currentTime + t0 + dur + 0.05);
}

export function chime() {
  if (muted) return;
  blip(660, 0, 0.2, 0.05);
}

export function unlock() {
  if (muted) return;
  blip(660, 0, 0.2, 0.05);
}

export function levelUpSound() {
  if (muted) return;
  blip(660, 0, 0.2, 0.05);
}

// No-ops kept so existing call sites (e.g. Chat.tsx while awaiting a response)
// don't need to change — the ambient "thinking" drone has been removed.
export function startHum() {}
export function stopHum() {}
