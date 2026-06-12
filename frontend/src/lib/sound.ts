let ctx: AudioContext | null = null;
let humOsc: OscillatorNode | null = null;
let humGain: GainNode | null = null;
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
  if (muted) stopHum();
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
  blip(660, 0, 0.25);
  blip(990, 0.12, 0.3);
}

export function unlock() {
  if (muted) return;
  blip(440, 0, 0.18, 0.05);
  blip(554, 0.1, 0.18, 0.05);
  blip(659, 0.2, 0.35, 0.06);
}

export function levelUpSound() {
  if (muted) return;
  [523, 659, 784, 1046].forEach((f, i) => blip(f, i * 0.1, 0.4, 0.07));
}

export function startHum() {
  if (muted || humOsc) return;
  const a = ac();
  humOsc = a.createOscillator();
  humGain = a.createGain();
  humOsc.type = "sine";
  humOsc.frequency.value = 110;
  humGain.gain.value = 0.015;
  humOsc.connect(humGain).connect(a.destination);
  humOsc.start();
}

export function stopHum() {
  if (humOsc) {
    try {
      humOsc.stop();
    } catch {
      /* already stopped */
    }
    humOsc.disconnect();
    humOsc = null;
    humGain = null;
  }
}
