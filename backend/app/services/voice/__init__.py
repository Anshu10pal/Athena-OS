"""Shared voice services: STT now, TTS in the next phase.

WHY THIS PACKAGE EXISTS
=======================
Before 2026-09-03 the voice stack had no shared layer, and the consequence was
measured rather than theorised. Two modules each constructed their own Whisper
model with DIFFERENT settings:

    oratory.analyze    word_timestamps=True, initial_prompt=<verbatim>,
                       suppress_tokens=[], vad_filter=False   -> fillers KEPT
    voice.transcribe   vad_filter=True, nothing else          -> fillers DROPPED

Both were "the STT path". Whichever one a caller happened to hit decided
whether "um" and "uh" survived, and the legacy interview page hit the one that
dropped them. Filler preservation is a hard requirement for this project, so a
setting that decides it cannot live in two places -- see
tests/test_voice_stt.py, which pins all four settings literally.

The 501 message constants live here rather than in an API module. They were in
`voice.py` and imported by `oratory.py`, which is the wrong direction: an API
module is not the home for a contract two API modules share.
"""

# One message, every call site, and it says what a 501 MEANS rather than what to
# type. The two predecessors disagreed with each other ("Run: pip install -r
# requirements-voice.txt" vs "Run: pip install faster-whisper") and both became
# actively misleading the moment that extras file was merged away -- they told a
# developer to install a hard dependency from a file that no longer exists.
NOT_INSTALLED_STT = (
    "Local STT is not installed. This should not occur in a properly-configured "
    "install — faster-whisper is a hard dependency in requirements.txt. "
    "Report as a defect."
)
# Names the CURRENT engines. It said "edge-tts and piper-tts" until Phase 6
# deleted edge-tts; a 501 naming a package the project no longer installs would
# send a developer to fix the wrong thing, which is exactly how the two
# predecessor messages went stale (they pointed at an extras file that had
# already been merged away).
NOT_INSTALLED_TTS = (
    "No TTS available. This should not occur in a properly-configured install "
    "— kokoro-onnx and piper-tts are hard dependencies in requirements.txt. "
    "Report as a defect."
)
