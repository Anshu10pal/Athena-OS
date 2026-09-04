"""VKI-9: Kokoro RTF vs onnxruntime intra-op thread count. MEASUREMENT ONLY.

Standalone by design. `tts.py` is NOT modified and NOT imported for synthesis:
kokoro_onnx builds its own session inside Kokoro.__init__ via
session.create_session(), which passes no SessionOptions, so the only way to set
intra_op_num_threads is to build the InferenceSession here and hand it to
Kokoro.from_session(). That keeps the commit to measurement + filings with no
code-path additions, which is the stronger of the two stated constraints.

What is replicated from tts.py::_synth_kokoro, exactly, so the numbers are
comparable to VKI-8's:
  - the same weight paths (via app.core.config.MODELS_DIR)
  - providers=["CPUExecutionProvider"]  (what resolve_providers() returns here)
  - the same espeak-ng wiring
  - k.create(text, voice="af_heart", speed=1.0, lang="en-us")
  - the same float32 -> 16-bit PCM WAV framing, so `audio seconds` is measured
    off the delivered artefact and not off a frame count

Egress is blocked for the whole run: weights are already fetched, and a fetch
attempt mid-measurement would be measuring a different thing (§17.34).

Usage:  vki9_measure.py <threads|default> <out.json>
"""
import io
import json
import os
import socket
import statistics
import sys
import time
import wave

os.environ["MODELS_OFFLINE"] = "1"

# ---- fixtures: byte-identical to VKI-8's, and the length is ASSERTED rather
# ---- than trusted. Three earlier drafts of this measurement mislabelled the
# ---- passage length (466 and 580 both reported as 673); the assert is the fix.
BASE = (
    "Remote work has reshaped how organisations think about collaboration. "
    "Teams that once relied on hallway conversations now depend on written communication, "
    "which rewards clarity and punishes ambiguity. Managers report that the hardest part "
    "is not tracking output but noticing when someone is struggling, because the informal "
    "signals that used to surface problems early simply are not there. Some companies have "
    "responded by scheduling deliberate unstructured time, an attempt to manufacture the "
    "spontaneity that offices produced for free. Whether that works remains genuinely open. "
    "The question now is which habits survive the return to shared physical space, and which "
    "quietly disappear once the meetings resume."
)
PASSAGE = BASE[:673]
QUESTION = "Tell me about a time you disagreed with a technical decision your team made."
assert len(PASSAGE) == 673, len(PASSAGE)
assert len(QUESTION) == 76, len(QUESTION)

RUNS = 3
MAX_ATTEMPTS = 6  # a discarded transient run must not silently shorten n


def block_egress():
    """Outbound only. Replacing socket.socket wholesale breaks asyncio's
    socketpair and produces failures indistinguishable from real fetches --
    that was a Phase 5 false positive, filed as tautological-check-adjacent."""
    attempts = []

    def no_connect(self, addr, *a, **k):
        attempts.append(addr)
        raise OSError("EGRESS BLOCKED")

    socket.socket.connect = no_connect
    socket.socket.connect_ex = lambda self, a, *x, **k: (attempts.append(a), 1)[1]
    socket.create_connection = lambda a, *x, **k: (
        attempts.append(a), (_ for _ in ()).throw(OSError("EGRESS BLOCKED")))[1]
    socket.getaddrinfo = lambda h, p, *a, **k: (
        attempts.append((h, p)), (_ for _ in ()).throw(OSError("EGRESS BLOCKED")))[1]
    return attempts


def build(threads):
    """A Kokoro bound to a session with intra_op_num_threads=threads.

    threads=None means "leave SessionOptions untouched", i.e. onnxruntime's
    default of 0/auto -- the configuration every number in VKI-8 was taken
    under. inter_op is HELD CONSTANT at the default (0/auto) throughout, and
    execution_mode stays ORT_SEQUENTIAL (the CPU default), under which inter-op
    threads are not used at all.
    """
    import onnxruntime as rt
    from kokoro_onnx import Kokoro

    from app.core.config import MODELS_DIR

    model = str(MODELS_DIR / "kokoro-v1.0.int8.onnx")
    voices = str(MODELS_DIR / "voices-v1.0.bin")
    for p in (model, voices):
        if not os.path.exists(p):
            raise SystemExit(f"STOP: weights missing at {p}")

    opts = rt.SessionOptions()
    if threads is not None:
        opts.intra_op_num_threads = threads
    session = rt.InferenceSession(model, opts, providers=["CPUExecutionProvider"])

    # Same espeak wiring as tts.py: espeakng-loader ships libespeak-ng in the
    # wheel, and phonemizer has to be pointed at it or it hunts for a system
    # install -- the thing that would break Windows parity.
    try:
        import espeakng_loader
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    except Exception as exc:
        print(f"  WARNING: espeak wiring failed: {exc}", flush=True)

    return Kokoro.from_session(session, voices), session


def wav_seconds(samples, rate):
    """Duration off the delivered WAV, framed exactly as tts.py frames it."""
    import numpy as np
    clipped = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    data = buf.getvalue()
    with wave.open(io.BytesIO(data)) as r:
        return r.getnframes() / r.getframerate(), len(data)


def timed(k, text):
    t0 = time.perf_counter()
    samples, rate = k.create(text, voice="af_heart", speed=1.0, lang="en-us")
    elapsed = time.perf_counter() - t0
    dur, nbytes = wav_seconds(samples, rate)
    if dur <= 0 or nbytes < 1000:
        raise RuntimeError(f"malformed audio: {dur=} {nbytes=}")
    return elapsed, dur, nbytes


def main():
    arg = sys.argv[1]
    threads = None if arg == "default" else int(arg)
    out_path = sys.argv[2]

    attempts = block_egress()
    label = "default(auto)" if threads is None else str(threads)
    print(f"\n=== intra_op_num_threads = {label} ===", flush=True)

    k, session = build(threads)
    eff = session.get_session_options()
    print(f"  session: intra_op={eff.intra_op_num_threads} "
          f"inter_op={eff.inter_op_num_threads} mode={eff.execution_mode} "
          f"providers={session.get_providers()}", flush=True)

    # Warm-up, excluded from every statistic. First call pays lazy-init costs
    # that belong to neither the engine nor the thread count.
    k.create("warm up", voice="af_heart", speed=1.0, lang="en-us")

    result = {"threads": label, "intra_op_effective": eff.intra_op_num_threads,
              "inter_op_effective": eff.inter_op_num_threads,
              "execution_mode": str(eff.execution_mode), "fixtures": {}}

    for name, text in (("673-char passage", PASSAGE), ("76-char question", QUESTION)):
        times, dur, discarded = [], None, []
        attempt = 0
        while len(times) < RUNS and attempt < MAX_ATTEMPTS:
            attempt += 1
            try:
                el, dur, nbytes = timed(k, text)
            except Exception as exc:               # discard, do not count
                discarded.append(f"{type(exc).__name__}: {exc}")
                print(f"  {name} run {len(times)+1}: DISCARDED ({exc})", flush=True)
                continue
            times.append(el)
            print(f"  {name} run {len(times)}/{RUNS}: {el:7.2f}s synth  "
                  f"{dur:6.2f}s audio  RTF {el/dur:5.2f}x  {nbytes/1e6:.2f} MB",
                  flush=True)
        if len(times) < RUNS:
            raise SystemExit(f"STOP: {name} could not complete {RUNS} clean runs "
                             f"({len(times)} of {RUNS}); discards={discarded}")
        med = statistics.median(times)
        result["fixtures"][name] = {
            "chars": len(text), "audio_seconds": round(dur, 3),
            "synth_median": round(med, 3), "synth_min": round(min(times), 3),
            "synth_max": round(max(times), 3),
            "rtf_median": round(med / dur, 4),
            "rtf_min": round(min(times) / dur, 4), "rtf_max": round(max(times) / dur, 4),
            "discarded": discarded,
        }
        print(f"  -> {name}: median {med:.2f}s ({min(times):.2f}, {max(times):.2f})  "
              f"RTF {med/dur:.2f}x", flush=True)

    result["connection_attempts"] = len(attempts)
    print(f"  connection attempts: {len(attempts)}", flush=True)

    existing = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            existing = json.load(f)
    existing[label] = result
    with open(out_path, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"  written -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
