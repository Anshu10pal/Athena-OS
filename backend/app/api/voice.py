"""Local voice endpoints.

STT: faster-whisper (CPU int8). TTS: edge-tts with a Piper fallback.

NO LONGER OPTIONAL. These were behind an extras file (requirements-voice.txt)
until 2026-09-03, and the extras file was never installed -- so every endpoint
here returned 501 and the frontend silently fell back to browser speech APIs,
discoverable only by calling them. The four packages are now hard dependencies
in requirements.txt: the app either boots with voice working or fails at build.

A 501 from this module therefore means the install is broken, not that a feature
is switched off, and the messages below say so.
"""
import io
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.security import get_current_user

router = APIRouter(prefix="/api/voice", tags=["voice"])

# One message, two call sites, and it says what a 501 now MEANS. The old
# messages ("Run: pip install -r requirements-voice.txt" here,
# "Run: pip install faster-whisper" in oratory.py) disagreed with each other,
# and both became actively misleading the moment the extras file was deleted --
# they told a developer to install something that is already a hard dependency,
# pointing at a file that no longer exists.
_NOT_INSTALLED_STT = (
    "Local STT is not installed. This should not occur in a properly-configured "
    "install \u2014 faster-whisper is a hard dependency in requirements.txt. "
    "Report as a defect."
)
_NOT_INSTALLED_TTS = (
    "No TTS available. This should not occur in a properly-configured install "
    "\u2014 edge-tts and piper-tts are hard dependencies in requirements.txt. "
    "Report as a defect."
)

_whisper_model = None


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user=Depends(get_current_user)):
    global _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(501, _NOT_INSTALLED_STT)
    if _whisper_model is None:
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    segments, _info = _whisper_model.transcribe(path, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments)
    return {"text": text}


@router.post("/speak")
async def speak(payload: dict, user=Depends(get_current_user)):
    text = (payload or {}).get("text", "")
    if not text:
        raise HTTPException(400, "No text provided")
    # Primary: Edge-TTS (free Microsoft neural voices, no key). Fallback: Piper (fully local).
    try:
        import edge_tts

        voice_name = getattr(user, "voice", None) or "en-US-AriaNeural"
        communicate = edge_tts.Communicate(text[:1500], voice=voice_name)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        if buf.getbuffer().nbytes > 0:
            return Response(content=buf.getvalue(), media_type="audio/mpeg")
    except ImportError:
        pass
    except Exception:
        pass  # offline or blocked -> try Piper
    try:
        from piper import PiperVoice
    except ImportError:
        raise HTTPException(501, _NOT_INSTALLED_TTS)
    import os
    import wave

    voice_path = os.environ.get("PIPER_VOICE", "voices/en_US-lessac-medium.onnx")
    if not os.path.exists(voice_path):
        raise HTTPException(501, _NOT_INSTALLED_TTS)
    voice = PiperVoice.load(voice_path)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize(text, wav)
    return Response(content=buf.getvalue(), media_type="audio/wav")
