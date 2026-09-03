"""The shared STT service, and the four settings filler preservation rests on.

WHY A PIN AND NOT JUST A UNIT TEST
==================================
`suppress_tokens=[]`, the verbatim `initial_prompt`, `word_timestamps=True` and
`vad_filter=False` are the difference between a transcript that keeps "um" and
one that quietly deletes it. Whisper's DEFAULT suppression list removes filler
tokens before output, so losing any of the four does not fail loudly -- it
produces fluent, plausible transcripts and a filler count that reads near-zero
regardless of how the person actually spoke.

That is unobservable from the outside, and it already happened once: this
configuration was correct in `oratory.analyze` and entirely absent from
`voice.transcribe`, so the project had two STT paths disagreeing about its own
hard requirement, with the legacy interview page wired to the wrong one.

So these tests pin the settings the way SPAN_MAX_WORDS is pinned -- including
the `initial_prompt` STRING literally, because a paraphrase of a prompt is a
different prompt and "looks about right" is not a property a guarantee can rest
on.
"""
import inspect
import pathlib

import pytest

from app.services.voice import NOT_INSTALLED_STT, NOT_INSTALLED_TTS
from app.services.voice import stt

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
SERVICE_FILE = APP_DIR / "services" / "voice" / "stt.py"


class TestTheFourSettingsArePinned:
    """All four, asserted exactly as they exist today."""

    def test_suppress_tokens_is_the_empty_list(self):
        assert stt.TRANSCRIBE_OPTIONS["suppress_tokens"] == [], (
            "suppress_tokens is no longer []. Whisper's DEFAULT suppression list "
            "deletes filler tokens before output, so this single setting is what "
            "makes 'um' and 'uh' survive at all. Filler preservation is a hard "
            "requirement for this project."
        )

    def test_initial_prompt_is_pinned_literally(self):
        expected = "So um, uh, I think, you know, like, basically, um yeah..."
        assert stt.VERBATIM_INITIAL_PROMPT == expected, (
            f"the verbatim initial_prompt changed.\n  was: {expected!r}\n"
            f"  now: {stt.VERBATIM_INITIAL_PROMPT!r}\n"
            "This is a PROMPT, not a description of one -- a reworded version is "
            "a different nudge to the decoder. If the change is deliberate, "
            "update this literal in the same commit and say in the message what "
            "it does to filler preservation."
        )
        assert stt.TRANSCRIBE_OPTIONS["initial_prompt"] == expected

    def test_word_timestamps_is_on(self):
        assert stt.TRANSCRIBE_OPTIONS["word_timestamps"] is True, (
            "word_timestamps off means no per-word times, which removes pause "
            "detection, pace-over-time, and any ability to LOCATE a filler "
            "rather than merely count it."
        )

    def test_vad_filter_is_off(self):
        assert stt.TRANSCRIBE_OPTIONS["vad_filter"] is False, (
            "vad_filter on removes the silence that pause metrics are computed "
            "from, and can clip a quiet filler at the start of a phrase -- the "
            "exact token this service exists to keep. It was ON in the old "
            "voice.transcribe, which is part of why that path dropped fillers."
        )

    def test_no_fifth_option_crept_in(self):
        # Not pedantry: an added option is a change to decoding behaviour that
        # nothing else in this file would notice.
        assert set(stt.TRANSCRIBE_OPTIONS) == {
            "word_timestamps", "initial_prompt", "suppress_tokens", "vad_filter"
        }, f"TRANSCRIBE_OPTIONS gained or lost a key: {sorted(stt.TRANSCRIBE_OPTIONS)}"

    def test_model_construction_is_cpu_only(self):
        # Hard constraint: CPU only, no CUDA, anywhere.
        assert stt.DEVICE == "cpu"
        assert stt.COMPUTE_TYPE == "int8"
        assert stt.MODEL_SIZE == "base"


class TestThereIsExactlyOneSTTConfiguration:
    """Enforced, not remembered. The defect being prevented is a SECOND
    configuration appearing somewhere else and disagreeing with this one, which
    is precisely the state the codebase was in before the extraction."""

    def _py_files(self):
        return [p for p in APP_DIR.rglob("*.py") if p != SERVICE_FILE]

    def test_no_whisper_model_is_constructed_outside_the_service(self):
        offenders = []
        for path in self._py_files():
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "WhisperModel(" in line and not line.lstrip().startswith("#"):
                    offenders.append(f"{path.relative_to(APP_DIR.parent)}:{i}")
        assert not offenders, (
            f"a second Whisper model is constructed at {offenders}. Every STT "
            "caller must go through app.services.voice.stt so there is one "
            "configuration and one set of loaded weights."
        )

    def test_no_transcribe_option_is_passed_outside_the_service(self):
        """Parsed, not grepped.

        The first version of this test scanned for the option names as
        substrings and skipped lines starting with `#` or a quote. It flagged
        PROSE inside voice.py's docstring ("used to call Whisper with
        vad_filter=True") -- a false positive that would have had to be
        suppressed with an exclusion, which is how a guard starts lying. The
        AST only sees real keyword arguments.
        """
        import ast
        forbidden = {"suppress_tokens", "initial_prompt", "vad_filter", "word_timestamps"}
        offenders = []
        for path in self._py_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg in forbidden:
                            offenders.append(
                                f"{path.relative_to(APP_DIR.parent)}:{node.lineno} {kw.arg}=")
        assert not offenders, (
            f"transcription options are passed outside the shared service: "
            f"{offenders}. That is exactly how the two disagreeing "
            "configurations arose."
        )

    def test_both_api_call_sites_import_the_service(self):
        for module in ("app/api/voice.py", "app/api/oratory.py"):
            src = (APP_DIR.parent / module).read_text(encoding="utf-8")
            assert "from app.services.voice import stt" in src, (
                f"{module} does not import the shared STT service"
            )


class TestTheContract:
    def test_transcribe_returns_words_and_transcript(self, monkeypatch):
        class FakeWord:
            def __init__(self, w, s, e): self.word, self.start, self.end = w, s, e

        class FakeSeg:
            words = [FakeWord(" um ", 0.0, 0.2), FakeWord(" Python ", 0.3, 0.8)]

        class FakeModel:
            def transcribe(self, path, **opts):
                # The options the service passes are asserted here too, so a
                # caller-side drift is caught even if the constant is intact.
                assert opts == stt.TRANSCRIBE_OPTIONS
                return [FakeSeg()], None

        monkeypatch.setattr(stt, "_model", FakeModel())
        out = stt.transcribe("/nonexistent.wav")
        assert out["words"] == [
            {"w": "um", "start": 0.0, "end": 0.2},
            {"w": "Python", "start": 0.3, "end": 0.8},
        ]
        assert out["transcript"] == "um Python"

    def test_word_keys_match_what_oratory_metrics_read(self, monkeypatch):
        """Oratory's filler, pause and pace code reads w/start/end. Renaming
        any of them would break metrics that no STT test would notice."""
        class FakeWord:
            def __init__(self): self.word, self.start, self.end = "uh", 1.0, 1.1
        class FakeSeg:
            words = [FakeWord()]
        class FakeModel:
            def transcribe(self, path, **opts): return [FakeSeg()], None
        monkeypatch.setattr(stt, "_model", FakeModel())
        word = stt.transcribe("/x.wav")["words"][0]
        assert set(word) == {"w", "start", "end"}

    def test_empty_audio_returns_empty_rather_than_raising(self, monkeypatch):
        # A recording with no speech is a real thing a user submits. The two
        # callers handle it differently on purpose (Oratory 400s, voice returns
        # ""), so the service must not decide for them.
        class FakeModel:
            def transcribe(self, path, **opts): return [], None
        monkeypatch.setattr(stt, "_model", FakeModel())
        out = stt.transcribe("/x.wav")
        assert out == {"words": [], "transcript": ""}

    def test_missing_dependency_raises_a_typed_error_carrying_the_501_text(self, monkeypatch):
        stt.reset_for_tests()
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def blocked(name, *a, **k):
            if name == "faster_whisper":
                raise ImportError("blocked for test")
            return real_import(name, *a, **k)

        monkeypatch.setattr("builtins.__import__", blocked)
        with pytest.raises(stt.STTUnavailable) as exc:
            stt._get_model()
        assert str(exc.value) == NOT_INSTALLED_STT
        stt.reset_for_tests()

    def test_the_501_messages_live_in_the_service_package(self):
        # They were in app/api/voice.py and imported by app/api/oratory.py --
        # an API module is not the home for a contract two API modules share.
        assert "hard dependenc" in NOT_INSTALLED_STT   # "dependency"
        assert "hard dependenc" in NOT_INSTALLED_TTS   # "dependencies"
        for module in ("app/api/voice.py", "app/api/oratory.py"):
            src = (APP_DIR.parent / module).read_text(encoding="utf-8")
            assert "_NOT_INSTALLED_STT = (" not in src, f"{module} redefines the message"


class TestSingleModelInstance:
    """One model, one load.

    Both API modules previously held their own `_whisper` global, so a process
    serving Oratory AND the voice endpoint loaded the weights TWICE and kept
    both. The first version of this test passed while asserting nothing -- the
    same tautological-check defect caught in the LLM-clustering prompt pin. It
    now counts constructions.
    """

    def test_the_model_is_constructed_once_and_reused(self, monkeypatch):
        import sys
        import types

        builds = {"n": 0}

        class FakeModel:
            def transcribe(self, path, **opts):
                return [], None

        def factory(*args, **kwargs):
            builds["n"] += 1
            return FakeModel()

        fake_mod = types.ModuleType("faster_whisper")
        fake_mod.WhisperModel = factory
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)

        stt.reset_for_tests()
        first = stt._get_model()
        second = stt._get_model()
        third = stt._get_model()
        assert builds["n"] == 1, (
            f"the model was constructed {builds['n']} times; the whole point of "
            "the shared service is one set of loaded weights"
        )
        assert first is second is third
        stt.reset_for_tests()

    def test_reset_actually_drops_the_cached_model(self, monkeypatch):
        # Otherwise the test above would pass for the wrong reason on a warm
        # module and prove nothing on a second run.
        import sys
        import types
        builds = {"n": 0}

        class FakeModel:
            pass

        fake_mod = types.ModuleType("faster_whisper")
        fake_mod.WhisperModel = lambda *a, **k: (builds.__setitem__("n", builds["n"] + 1)
                                                 or FakeModel())
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)
        stt.reset_for_tests()
        stt._get_model()
        stt.reset_for_tests()
        stt._get_model()
        assert builds["n"] == 2, "reset_for_tests did not drop the cached model"
        stt.reset_for_tests()

    def test_is_available_does_not_load_the_model(self):
        """A readiness probe that downloads 142 MB is not a readiness probe --
        see docs/voice-known-issues.md VKI-4."""
        stt.reset_for_tests()
        assert stt.is_available() is True
        assert stt._model is None, "is_available() constructed the model"
