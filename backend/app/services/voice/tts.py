"""Text-to-speech behind ONE interface, engine chosen by TTS_ENGINE.

WHY THIS EXISTS
===============
Before 2026-09-03 there was no TTS interface. `edge_tts` was constructed
directly in two places -- `voice.speak` and `communication._synthesize` -- with
duplicated try/except blocks, a Piper fallback that had never worked, and no way
to answer "which engine is actually running" from outside either call site.

Both defects were measured, not inferred: `communication._synthesize` swallowed
every failure into `return b""` (VKI-1) and the Piper fallback's pinned version
could not even be installed on this runtime (VKI-3).

ENGINE CHOICE, and it was decided on measurement
================================================
`kokoro` here means **kokoro-onnx**, not the `kokoro` PyPI package. That is not
a preference:

    pip install --dry-run kokoro       -> cuda-toolkit, nvidia-cublas,
                                          nvidia-cudnn, nvidia-cufft, ...
    pip install --dry-run kokoro-onnx  -> dlinfo, espeakng-loader,
                                          kokoro-onnx, phonemizer

The torch-based package pulls CUDA wheels, which is disqualifying under this
project's CPU-only constraint before image size is even discussed. kokoro-onnx
runs on the `onnxruntime` already present for FastEmbed, and `espeakng-loader`
ships `libespeak-ng` INSIDE the wheel -- so phonemisation needs no system
package, which is what keeps Windows dev parity without WSL.

The int8 model (88 MB) is used rather than fp32 (310 MB) or fp16 (169 MB):
int8 quantisation targets CPU inference, and it matches the
`compute_type="int8"` this project already chose for faster-whisper.

EDGE-TTS IS GONE, AS OF PHASE 6 (2026-09-03)
============================================
It was the original primary: a websocket to a Microsoft endpoint, which meant
every spoken response needed a network round-trip, it broke behind the corporate
proxy, and every utterance left the machine. Kokoro replaced it as primary in
Phase 4; the deletion waited for Phase 6 to MEASURE that no endpoint regressed,
so that Phase 5's weight-baking kept a rollback path not dependent on the same
weights.

Removing it dropped 9 packages and 11 MB, including the entire aiohttp
websocket stack, which nothing else in this project required.

It is not coming back as a fallback. A network fallback underneath a local-first
primary is precisely the configuration where an offline guarantee stops holding
without anyone noticing -- the defect class Phase 5 closed. There are now two
engines and both are local.
"""
import io
import logging
import os
import threading
import wave
from typing import Optional

from app.core.config import MODELS_DIR
from app.services.voice import NOT_INSTALLED_TTS

logger = logging.getLogger("athena.voice.tts")

# ---------------------------------------------------------------------------
# Engine names. Literals, pinned by tests/test_voice_tts.py -- a name that
# exists in the env var, the dispatch table and a docstring but nowhere as a
# constant is three sources of truth.
# ---------------------------------------------------------------------------
ENGINE_KOKORO = "kokoro"
ENGINE_PIPER = "piper"

# Order matters: primary first, then fallbacks in the order they are tried.
# Both entries are LOCAL. `edge` was the third entry until Phase 6; see the
# module docstring for why a network engine is not welcome back here.
ENGINE_ORDER = (ENGINE_KOKORO, ENGINE_PIPER)

# Engines that once existed, mapped to what to do instead. Kept so that a
# deploy still carrying TTS_ENGINE=edge gets a sentence naming the removal
# rather than a bare "not a known engine", which would send an operator looking
# for a typo that is not there.
RETIRED_ENGINES = {
    "edge": "edge-tts was removed in Phase 6 (network dependency, sent audio "
            "to Microsoft). Unset TTS_ENGINE to use kokoro.",
}
DEFAULT_ENGINE = ENGINE_KOKORO

# Env var name is itself a constant so the pin test asserts the same string the
# code reads.
ENGINE_ENV_VAR = "TTS_ENGINE"

# Weight locations. Overridable so Phase 5's image can put them anywhere, with
# defaults pointing at the local `models/` directory an operator populates via
# scripts/fetch_models.sh.
# Derived from the ONE model root in app.core.config rather than re-deriving a
# path from __file__ -- four loaders resolving "the models directory"
# independently is four chances to disagree.
KOKORO_MODEL_PATH = os.environ.get(
    "KOKORO_MODEL_PATH", str(MODELS_DIR / "kokoro-v1.0.int8.onnx"))
KOKORO_VOICES_PATH = os.environ.get(
    "KOKORO_VOICES_PATH", str(MODELS_DIR / "voices-v1.0.bin"))
PIPER_VOICE_PATH = os.environ.get(
    "PIPER_VOICE", str(MODELS_DIR / "piper" / "en_US-lessac-medium.onnx"))

# Kokoro voice used when a caller passes nothing, or passes a voice name Kokoro
# does not know.
#
# THIS OUTLIVES EDGE-TTS AND MUST. The `user.voice` column still holds edge-tts
# voice IDs (e.g. "en-US-AriaNeural") for anyone who set one before Phase 6 --
# deleting the engine does not rewrite stored user rows. So an unknown voice name
# has to degrade to a working default rather than fail. Mapping every legacy name
# onto a Kokoro equivalent would be inventing a compatibility table nobody asked
# for; falling back to one known-good voice and SAYING SO in the log is honest.
KOKORO_DEFAULT_VOICE = "af_heart"
KOKORO_SAMPLE_RATE = 24000


class TTSUnavailable(RuntimeError):
    """No engine could produce audio.

    Raised, never returned as empty bytes. `communication._synthesize` returning
    b"" on failure is VKI-1: the caller then served HTTP 200 with silence, which
    is the plausible-rather-than-broken shape. A caller that wants to degrade
    can catch this; it can no longer do so by accident.
    """

    def __init__(self, message: str = NOT_INSTALLED_TTS):
        super().__init__(message)


_kokoro = None
_lock = threading.Lock()


def configured_engine() -> str:
    """The engine name from the environment, validated.

    An unknown value is a configuration error and says so rather than silently
    falling back to the default -- a typo'd TTS_ENGINE that quietly ran the
    primary engine would be indistinguishable from correct configuration.
    """
    name = (os.environ.get(ENGINE_ENV_VAR) or DEFAULT_ENGINE).strip().lower()
    if name not in ENGINE_ORDER:
        retired = RETIRED_ENGINES.get(name)
        raise ValueError(
            f"{ENGINE_ENV_VAR}={name!r} is not a known engine. "
            f"Known: {', '.join(ENGINE_ORDER)}."
            + (f" {retired}" if retired else "")
        )
    return name


def _pcm_to_wav(samples, sample_rate: int) -> bytes:
    """float32 [-1,1] -> 16-bit PCM WAV bytes."""
    import numpy as np

    clipped = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _get_kokoro():
    global _kokoro
    if _kokoro is not None:
        return _kokoro
    with _lock:
        if _kokoro is None:
            try:
                from kokoro_onnx import Kokoro
            except ImportError as exc:
                raise TTSUnavailable(
                    "kokoro-onnx is not installed. This should not occur in a "
                    "properly-configured install."
                ) from exc
            for path, label in ((KOKORO_MODEL_PATH, "model"),
                                (KOKORO_VOICES_PATH, "voices")):
                if not os.path.exists(path):
                    raise TTSUnavailable(
                        f"Kokoro {label} weights missing at {path}. Run "
                        "scripts/fetch_models.sh, or use a build that fetched them "
                        "with the weights baked in (see Phase 5)."
                    )
            # espeakng-loader ships libespeak-ng in the wheel; phonemizer needs
            # to be told where. Without this it looks for a SYSTEM espeak-ng,
            # which is the thing that would break Windows parity.
            try:
                import espeakng_loader
                from phonemizer.backend.espeak.wrapper import EspeakWrapper

                EspeakWrapper.set_library(espeakng_loader.get_library_path())
                EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
            except Exception:
                logger.warning("could not point phonemizer at the bundled "
                               "espeak-ng; falling back to a system install",
                               exc_info=True)
            logger.info("loading kokoro-onnx int8 from %s", KOKORO_MODEL_PATH)
            _kokoro = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
    return _kokoro


def _synth_kokoro(text: str, voice: Optional[str]) -> bytes:
    k = _get_kokoro()
    name = voice or KOKORO_DEFAULT_VOICE
    if name not in getattr(k, "voices", {}):
        if voice:
            logger.info("kokoro does not know voice %r; using %r",
                        voice, KOKORO_DEFAULT_VOICE)
        name = KOKORO_DEFAULT_VOICE
    samples, sample_rate = k.create(text, voice=name, speed=1.0, lang="en-us")
    return _pcm_to_wav(samples, sample_rate)


def _synth_piper(text: str, voice: Optional[str]) -> bytes:
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise TTSUnavailable("piper-tts is not installed.") from exc
    path = voice if (voice and os.path.exists(voice)) else PIPER_VOICE_PATH
    if not os.path.exists(path):
        # THE HONEST STATE, and it is deliberate rather than an oversight. See
        # docs/voice-known-issues.md VKI-5: the Piper voice file is NOT
        # committed (60 MB, and git keeps a binary forever), so this fallback
        # boots weightless and reports itself broken until an operator supplies
        # weights or the build fetches them. It does not pretend.
        #
        # RAISED IN COST BY PHASE 6: with edge-tts deleted this is the ONLY
        # fallback, so a weightless Piper means Kokoro failing has nothing
        # behind it. engine_status() reports that state rather than hiding it,
        # and scripts/fetch_models.sh fetches the file -- but the exposure is
        # real and is recorded against VKI-5.
        raise TTSUnavailable(
            f"Piper voice file missing at {path}. The Piper fallback ships "
            "WITHOUT weights by design -- run scripts/fetch_models.sh or "
            "use an image with them baked in. See docs/voice-known-issues.md "
            "VKI-5."
        )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        PiperVoice.load(path).synthesize_wav(text, w)
    return buf.getvalue()


# Both engines emit WAV now that edge-tts's audio/mpeg is gone. The mapping is
# kept rather than collapsed to a constant: it is what pins "every engine
# declares a media type", and a third engine arriving with a different container
# should have to add a row here.
MEDIA_TYPES = {ENGINE_KOKORO: "audio/wav",
               ENGINE_PIPER: "audio/wav"}


async def synthesize(text: str, voice: Optional[str] = None) -> tuple[bytes, str, str]:
    """text -> (audio_bytes, media_type, engine_that_produced_it).

    STILL `async` even though no engine awaits anything now that edge-tts is
    gone. Both call sites (`voice.speak`, `communication._synthesize`) await
    this, and breaking a shared interface is not part of a deletion whose gate
    was "no endpoint regresses". Both remaining engines are CPU-bound and block
    the event loop while they run -- true before this commit too, filed rather
    than fixed here because moving them to a threadpool changes concurrency
    behaviour and belongs with the latency work in VKI-8.

    Returns the engine name because a caller that cannot tell which engine ran
    cannot report a degraded state -- which is how VKI-1 was able to serve
    silence with a 200. Callers may ignore it; they can no longer be unable to
    know it.

    Tries the configured engine first, then the remaining engines in
    ENGINE_ORDER. Every failure is logged WITH its exception; the bare
    `except Exception: pass` this replaces is why an operator could not
    distinguish a blocked proxy from a missing package from a bad voice name.
    """
    if not text or not text.strip():
        raise ValueError("no text to synthesize")

    start = configured_engine()
    order = [start] + [e for e in ENGINE_ORDER if e != start]
    errors: list[str] = []
    for engine in order:
        try:
            if engine == ENGINE_KOKORO:
                audio = _synth_kokoro(text, voice)
            else:
                audio = _synth_piper(text, voice)
            if engine != start:
                logger.warning("TTS fell back from %s to %s", start, engine)
            return audio, MEDIA_TYPES[engine], engine
        except Exception as exc:  # noqa: BLE001 -- recorded, then next engine
            errors.append(f"{engine}: {type(exc).__name__}: {exc}")
            logger.warning("TTS engine %s failed: %s", engine, exc)
    raise TTSUnavailable(
        NOT_INSTALLED_TTS + " Tried " + "; ".join(errors)
    )


def engine_status() -> dict:
    """Per-engine readiness, without synthesising anything.

    This is the "does not silently ship a broken fallback" surface. It reports
    each engine as ready or names exactly what is missing, so
    `TTS_ENGINE=piper` on a machine with no voice file is a visible, reportable
    state rather than a runtime surprise.
    """
    out: dict = {"configured": None, "engines": {}}
    try:
        out["configured"] = configured_engine()
    except ValueError as exc:
        out["configured_error"] = str(exc)

    try:
        import kokoro_onnx  # noqa: F401
        missing = [p for p in (KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
                   if not os.path.exists(p)]
        out["engines"][ENGINE_KOKORO] = (
            {"ready": True} if not missing
            else {"ready": False, "reason": f"weights missing: {missing}"})
    except ImportError:
        out["engines"][ENGINE_KOKORO] = {"ready": False, "reason": "kokoro-onnx not installed"}

    try:
        import piper  # noqa: F401
        out["engines"][ENGINE_PIPER] = (
            {"ready": True} if os.path.exists(PIPER_VOICE_PATH)
            else {"ready": False,
                  "reason": f"voice file missing at {PIPER_VOICE_PATH} "
                            "(ships weightless by design -- VKI-5)"})
    except ImportError:
        out["engines"][ENGINE_PIPER] = {"ready": False, "reason": "piper-tts not installed"}

    return out


def reset_for_tests() -> None:
    global _kokoro
    with _lock:
        _kokoro = None
