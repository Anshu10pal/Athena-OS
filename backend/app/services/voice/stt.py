"""Speech-to-text, one configuration, one model instance.

THE FOUR SETTINGS BELOW ARE THE WHOLE POINT OF THIS MODULE
==========================================================
`suppress_tokens=[]`, the verbatim `initial_prompt`, `word_timestamps=True` and
`vad_filter=False` are what make fillers survive transcription. Whisper's
DEFAULT behaviour deletes them -- `suppress_tokens` has a built-in list that
removes filler tokens before output, which is why an un-configured transcript
comes back fluent and a filler count computed from it reads near-zero
regardless of how the person actually spoke.

That configuration existed and was correct in exactly one place
(`oratory.analyze`) and was entirely absent from the other STT endpoint
(`voice.transcribe`), which passed `vad_filter=True` and nothing else. So the
project had two STT paths that disagreed about its own hard requirement, and
the legacy interview page was wired to the wrong one.

Extracted here so the answer is the same wherever it is asked, and pinned by
tests/test_voice_stt.py so a drift in any one of the four fails a test rather
than silently producing clean transcripts. That test asserts the
`initial_prompt` STRING literally: a paraphrase of it is a different prompt, and
"looks about right" is not a property a filler-preservation guarantee can rest
on.

ONE MODEL INSTANCE, not two. `oratory` and `voice` each held their own
module-global, so a process that served both endpoints loaded the weights twice.
"""
import logging
import threading
from typing import Optional

from app.core.config import MODELS_DIR, MODELS_OFFLINE
from app.services.voice import NOT_INSTALLED_STT

logger = logging.getLogger("athena.voice.stt")

# ---------------------------------------------------------------------------
# Model construction. Same values both call sites used independently, so this
# is a consolidation and not a change.
# ---------------------------------------------------------------------------
MODEL_SIZE = "base"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Project-relative, and OFFLINE-ENFORCED by default. `download_root` puts the
# weights inside the repo directory (the only place Render documents as present
# at runtime) and `local_files_only` makes a runtime fetch IMPOSSIBLE rather
# than merely unnecessary -- which is what turns VKI-4 from "the cache happened
# to be warm" into a property a test can assert.
WHISPER_DOWNLOAD_ROOT = str(MODELS_DIR / "whisper")

# ---------------------------------------------------------------------------
# THE VERBATIM CONFIG. Do not change any of these four without reading
# tests/test_voice_stt.py, which pins them, and without saying in the commit
# message what it does to filler preservation.
# ---------------------------------------------------------------------------

# Nudges the decoder toward a disfluent register so it does not "tidy" speech.
# The exact string matters and is pinned: it is a prompt, not a description of
# one.
VERBATIM_INITIAL_PROMPT = "So um, uh, I think, you know, like, basically, um yeah..."

TRANSCRIBE_OPTIONS: dict = {
    # Per-word start/end times. Needed for pause detection, pace-over-time and
    # any end-of-turn work; also the only way a filler can be located rather
    # than merely counted.
    "word_timestamps": True,
    # See VERBATIM_INITIAL_PROMPT.
    "initial_prompt": VERBATIM_INITIAL_PROMPT,
    # THE one that actually preserves fillers. Whisper's default suppression
    # list removes them before they reach output.
    "suppress_tokens": [],
    # OFF deliberately. Voice-activity filtering removes the silence that pause
    # metrics are computed from, and it can clip a quiet filler at the start of
    # a phrase -- which is the exact token this module exists to keep.
    "vad_filter": False,
}


class STTUnavailable(RuntimeError):
    """faster-whisper is not importable.

    Carries NOT_INSTALLED_STT as its message so API layers can map it to a 501
    without each of them re-wording the reason. Raised rather than returned:
    an empty transcript and a broken install must not look alike to a caller.
    """

    def __init__(self, message: str = NOT_INSTALLED_STT):
        super().__init__(message)


_model = None
_lock = threading.Lock()


def _get_model():
    """The single process-wide model, built lazily under a lock.

    Locked because FastAPI serves requests on a threadpool and two concurrent
    first-requests would otherwise both construct a model -- loading the weights
    twice and throwing one away. The old per-module globals had the same race
    and, being two globals, also kept two models when both endpoints were used.
    """
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise STTUnavailable() from exc
            logger.info("loading faster-whisper %s (%s/%s)",
                        MODEL_SIZE, DEVICE, COMPUTE_TYPE)
            _model = WhisperModel(
                MODEL_SIZE,
                device=DEVICE,
                compute_type=COMPUTE_TYPE,
                download_root=WHISPER_DOWNLOAD_ROOT,
                local_files_only=MODELS_OFFLINE,
            )
    return _model


def transcribe(audio_path: str) -> dict:
    """Audio file -> {"words": [{"w", "start", "end"}], "transcript": str}.

    `words` keeps the key names the existing Oratory metrics code already reads
    (`w`/`start`/`end`), so consolidating the config did not require touching
    the filler, pause and pace calculations that consume it -- which is the
    point: this change is about WHERE the settings live, not what they produce.

    An empty result is returned as empty rather than raised on. A recording with
    no speech in it is a real thing a user can submit, and the callers already
    decide what to do about it differently: Oratory returns 400 "No speech
    detected", while `voice.transcribe` returns an empty string so a
    voice-to-text field simply stays as it was.
    """
    model = _get_model()
    segments, _info = model.transcribe(audio_path, **TRANSCRIBE_OPTIONS)
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "start": w.start, "end": w.end})
    return {"words": words, "transcript": " ".join(w["w"] for w in words)}


def is_available() -> bool:
    """Whether STT can run, without constructing the model.

    For health checks and the wired-gate test. Deliberately does NOT warm the
    model: a readiness probe that downloads 142 MB is not a readiness probe
    (see docs/voice-known-issues.md VKI-4).
    """
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def reset_for_tests() -> None:
    """Drop the cached model. Exposed so tests can assert construction
    behaviour without reaching into a module global from outside."""
    global _model
    with _lock:
        _model = None
