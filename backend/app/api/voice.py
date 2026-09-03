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
from app.services.voice import NOT_INSTALLED_TTS
from app.services.voice import stt

router = APIRouter(prefix="/api/voice", tags=["voice"])

# The 501 messages now live in app/services/voice/ -- an API module was the
# wrong home for a contract two API modules share, and the note left in the
# previous commit said so.


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Audio -> text, through the SHARED verbatim STT service.

    BEHAVIOUR CHANGE, and it is the point of the extraction. This endpoint used
    to call Whisper with `vad_filter=True` and no other options, which meant
    Whisper's default token suppression DELETED fillers -- so the legacy
    interview page and the chat mic, both of which post here, silently received
    tidied transcripts while Oratory received verbatim ones. Filler preservation
    is a hard requirement for this project, so the two paths cannot disagree
    about it. Both now use the same configuration.

    The response shape is unchanged (`{"text": ...}`): `InterviewArena.tsx:145`
    and `Chat.tsx` destructure `text`, and this phase is about where the
    settings live, not about breaking callers.
    """
    try:
        result = stt.transcribe(await _spool(file))
    except stt.STTUnavailable as exc:
        raise HTTPException(501, str(exc))
    return {"text": result["transcript"]}


async def _spool(file: UploadFile) -> str:
    """Upload -> a path on disk, because faster-whisper reads a file.

    Suffix kept as `.webm` since that is what every current caller sends
    (MediaRecorder default); the decoder sniffs the container rather than
    trusting the extension, so a `.wav` upload also works -- which is what the
    wired-gate test relies on.
    """
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(data)
        return tmp.name


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
        raise HTTPException(501, NOT_INSTALLED_TTS)
    import os
    import wave

    voice_path = os.environ.get("PIPER_VOICE", "voices/en_US-lessac-medium.onnx")
    if not os.path.exists(voice_path):
        raise HTTPException(501, NOT_INSTALLED_TTS)
    voice = PiperVoice.load(voice_path)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize(text, wav)
    return Response(content=buf.getvalue(), media_type="audio/wav")
