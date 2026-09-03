"""Shared TTS interface: engine pins, enforcement, and the round-trip gate.

Mirrors tests/test_voice_stt.py deliberately. The defect being prevented is the
same one in a different medium: a setting or an engine choice living in two
places, disagreeing, with nothing failing loudly.
"""
import ast
import asyncio
import os
import pathlib

import pytest

from app.services.voice import NOT_INSTALLED_TTS, stt, tts

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
TTS_FILE = APP_DIR / "services" / "voice" / "tts.py"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "voice" / "kokoro_roundtrip.wav"

# ---------------------------------------------------------------------------
# THE PINNED GATE. Set before the first measurement and recorded in
# tests/fixtures/voice/PROVENANCE.md, including why the first fixture text was
# replaced (Whisper rendered the spoken number "three fifteen" as "3 .15", so
# the anchor was defeated by numeral normalisation rather than by a
# transcription failure).
# ---------------------------------------------------------------------------
FIXTURE_TEXT = "The meeting starts on Thursday and the client will review the design."
EXPECTED_WORDS = 12
WORD_TOLERANCE = 1
CONTENT_ANCHORS = ("meeting", "thursday", "design")


class TestEngineNamesArePinned:
    """Literals, because an engine name that appears in the env var, the
    dispatch and a docstring but nowhere as a constant is three sources of
    truth."""

    def test_engine_name_literals(self):
        assert tts.ENGINE_KOKORO == "kokoro"
        assert tts.ENGINE_PIPER == "piper"
        assert tts.ENGINE_EDGE == "edge"

    def test_env_var_name_is_pinned(self):
        assert tts.ENGINE_ENV_VAR == "TTS_ENGINE"

    def test_kokoro_is_the_default_and_edge_is_last(self):
        assert tts.DEFAULT_ENGINE == tts.ENGINE_KOKORO, (
            "Kokoro must be the primary engine -- that is the whole point of the "
            "migration away from edge-tts, which is a network call to Microsoft."
        )
        assert tts.ENGINE_ORDER == ("kokoro", "piper", "edge"), (
            f"engine order changed to {tts.ENGINE_ORDER}. Order is the fallback "
            "sequence: local-primary, local-fallback, network-last."
        )

    def test_no_fourth_engine_crept_in(self):
        assert set(tts.ENGINE_ORDER) == {"kokoro", "piper", "edge"}
        assert set(tts.MEDIA_TYPES) == set(tts.ENGINE_ORDER), (
            "an engine exists without a declared media type, or vice versa"
        )

    def test_kokoro_uses_the_int8_model(self):
        # CPU-only constraint, and consistency with faster-whisper's int8.
        assert "int8" in tts.KOKORO_MODEL_PATH, (
            f"Kokoro model path is {tts.KOKORO_MODEL_PATH!r}. int8 (88 MB) is "
            "chosen over fp32 (310 MB) for CPU inference; a change here is a "
            "change to image size and inference cost."
        )

    def test_configured_engine_rejects_an_unknown_name(self, monkeypatch):
        # A typo'd TTS_ENGINE that silently ran the default would be
        # indistinguishable from correct configuration.
        monkeypatch.setenv("TTS_ENGINE", "elevenlabs")
        with pytest.raises(ValueError, match="not a known engine"):
            tts.configured_engine()

    def test_configured_engine_defaults_when_unset(self, monkeypatch):
        monkeypatch.delenv("TTS_ENGINE", raising=False)
        assert tts.configured_engine() == tts.ENGINE_KOKORO

    @pytest.mark.parametrize("name", ["kokoro", "piper", "edge", "KOKORO", " edge "])
    def test_configured_engine_accepts_every_known_name(self, monkeypatch, name):
        monkeypatch.setenv("TTS_ENGINE", name)
        assert tts.configured_engine() in tts.ENGINE_ORDER


class TestThereIsExactlyOneTTSImplementation:
    """Enforced, not remembered -- same shape as the STT enforcement tests.

    edge-tts is still INSTALLED and `TTS_ENGINE=edge` still works: deletion is a
    Phase 6 change bundled with the pip removal, so Phase 5's weight-baking has
    a rollback path. What is forbidden is a second CALL SITE.
    """

    def _other_py_files(self):
        return [p for p in APP_DIR.rglob("*.py") if p != TTS_FILE]

    def test_no_edge_tts_import_outside_the_tts_service(self):
        """AST-parsed, not grepped.

        A grep finds the words "edge_tts" and "edge-tts" in voice.py's docstring
        and in the 501 message text -- both legitimate prose. Suppressing those
        with an exclusion list is how a guard starts lying, so the check looks
        at real import statements instead.
        """
        offenders = []
        for path in self._other_py_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] == "edge_tts":
                            offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] == "edge_tts":
                        offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
        assert not offenders, (
            f"edge_tts is imported outside the TTS service at {offenders}. Every "
            "caller must go through app.services.voice.tts.synthesize so the "
            "engine is a configuration choice and not a hard-coded one."
        )

    def test_no_kokoro_or_piper_import_outside_the_tts_service(self):
        offenders = []
        for path in self._other_py_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [(node.module or "").split(".")[0]]
                for m in mods:
                    if m in {"kokoro_onnx", "piper"}:
                        offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno} {m}")
        assert not offenders, f"engine imported directly outside the service: {offenders}"

    def test_both_tts_call_sites_use_the_interface(self):
        for module, needle in (("app/api/voice.py", "tts.synthesize"),
                               ("app/api/communication.py", "tts.synthesize")):
            src = (APP_DIR.parent / module).read_text(encoding="utf-8")
            assert needle in src, f"{module} does not call the shared interface"


class TestFailuresRaiseRatherThanReturningEmptyBytes:
    def test_unavailable_carries_the_shared_501_text(self):
        assert NOT_INSTALLED_TTS in str(tts.TTSUnavailable())

    def test_empty_text_is_a_value_error_not_silent_empty_audio(self):
        with pytest.raises(ValueError):
            asyncio.run(tts.synthesize("   "))

    def test_all_engines_failing_raises_with_every_reason_named(self, monkeypatch):
        """The bare `except Exception: pass` this replaces is why an operator
        could not distinguish a blocked proxy from a missing package."""
        monkeypatch.setattr(tts, "_synth_kokoro",
                            lambda t, v: (_ for _ in ()).throw(RuntimeError("no weights")))
        monkeypatch.setattr(tts, "_synth_piper",
                            lambda t, v: (_ for _ in ()).throw(RuntimeError("no voice file")))
        async def edge_boom(t, v):
            raise RuntimeError("proxy blocked")
        monkeypatch.setattr(tts, "_synth_edge", edge_boom)
        with pytest.raises(tts.TTSUnavailable) as exc:
            asyncio.run(tts.synthesize("hello"))
        msg = str(exc.value)
        for reason in ("no weights", "no voice file", "proxy blocked"):
            assert reason in msg, f"{reason!r} was swallowed instead of reported"

    def test_fallback_order_is_followed_and_the_engine_is_reported(self, monkeypatch):
        monkeypatch.setenv("TTS_ENGINE", "kokoro")
        monkeypatch.setattr(tts, "_synth_kokoro",
                            lambda t, v: (_ for _ in ()).throw(RuntimeError("down")))
        monkeypatch.setattr(tts, "_synth_piper", lambda t, v: b"PIPERBYTES")
        audio, media, engine = asyncio.run(tts.synthesize("hello"))
        assert audio == b"PIPERBYTES"
        assert engine == "piper", "the caller cannot tell which engine ran"
        assert media == "audio/wav"


class TestEngineStatusIsHonest:
    """The 'does not silently ship a broken fallback' surface."""

    def test_status_reports_every_engine(self):
        s = tts.engine_status()
        assert set(s["engines"]) == set(tts.ENGINE_ORDER)

    def test_piper_reports_broken_when_its_voice_file_is_absent(self, monkeypatch):
        monkeypatch.setattr(tts, "PIPER_VOICE_PATH", "/definitely/not/here.onnx")
        s = tts.engine_status()
        piper = s["engines"]["piper"]
        assert piper["ready"] is False, (
            "Piper claimed ready with no voice file. Shipping a never-worked "
            "fallback that reports itself healthy is the defect VKI-5 exists to "
            "prevent."
        )
        assert "VKI-5" in piper["reason"] or "missing" in piper["reason"]

    def test_status_does_not_synthesise_anything(self, monkeypatch):
        called = {"n": 0}
        monkeypatch.setattr(tts, "_synth_kokoro",
                            lambda t, v: called.__setitem__("n", called["n"] + 1))
        tts.engine_status()
        assert called["n"] == 0, "a readiness probe synthesised audio"


class TestRoundTripWiredGate:
    """Kokoro audio -> shared STT -> transcript. The real gate.

    Runs against the COMMITTED fixture so it works on a checkout with no model
    weights; the live-generation variant below skips when weights are absent.
    Tolerance is +/-1 word plus three content anchors, pinned before the first
    measurement -- not string equality, because Whisper on Kokoro on CPU is not
    deterministic and an exact-match assertion would be a flaky test pretending
    to be a strict one.
    """

    def test_the_committed_fixture_exists_with_provenance(self):
        assert FIXTURE.exists(), f"missing round-trip fixture at {FIXTURE}"
        prov = FIXTURE.parent / "PROVENANCE.md"
        assert prov.exists(), "fixture has no provenance record"
        text = prov.read_text(encoding="utf-8")
        assert "kokoro-onnx==0.6.1" in text and "2026-09-03" in text

    @pytest.mark.skipif(not stt.is_available(), reason="faster-whisper not installed")
    def test_kokoro_audio_round_trips_through_the_shared_stt_service(self):
        out = stt.transcribe(str(FIXTURE))
        words = [w["w"] for w in out["words"]]
        transcript = out["transcript"].lower()

        assert abs(len(words) - EXPECTED_WORDS) <= WORD_TOLERANCE, (
            f"round-trip word count {len(words)}, expected "
            f"{EXPECTED_WORDS}+/-{WORD_TOLERANCE}.\n  transcript: {out['transcript']!r}"
        )
        missing = [a for a in CONTENT_ANCHORS if a not in transcript]
        assert not missing, (
            f"content anchors lost in round-trip: {missing}\n"
            f"  transcript: {out['transcript']!r}"
        )
        assert all("start" in w and "end" in w for w in out["words"]), (
            "word timings absent -- the verbatim config has drifted"
        )

    @pytest.mark.skipif(
        not (os.path.exists(tts.KOKORO_MODEL_PATH) and os.path.exists(tts.KOKORO_VOICES_PATH)),
        reason="Kokoro weights not present (run scripts/fetch_voice_models.sh)")
    def test_live_kokoro_generation_still_round_trips(self, monkeypatch):
        monkeypatch.setenv("TTS_ENGINE", "kokoro")
        audio, media, engine = asyncio.run(tts.synthesize(FIXTURE_TEXT))
        assert engine == "kokoro" and media == "audio/wav" and len(audio) > 10_000
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio)
            path = tmp.name
        out = stt.transcribe(path)
        words = [w["w"] for w in out["words"]]
        assert abs(len(words) - EXPECTED_WORDS) <= WORD_TOLERANCE, (
            f"live round-trip word count {len(words)}: {out['transcript']!r}")
        low = out["transcript"].lower()
        assert not [a for a in CONTENT_ANCHORS if a not in low], out["transcript"]
