"""Local voice endpoints.

STT and TTS both go through app/services/voice/ -- this module is transport only.

NO LONGER OPTIONAL. These were behind an extras file (requirements-voice.txt)
until 2026-09-03, and the extras file was never installed -- so every endpoint
here returned 501 and the frontend silently fell back to browser speech APIs,
discoverable only by calling them. The four packages are now hard dependencies
in requirements.txt: the app either boots with voice working or fails at build.

A 501 from this module therefore means the install is broken, not that a feature
is switched off, and the messages below say so.
"""
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.security import get_current_user
from app.services.voice import stt, tts

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
    """Text -> audio, through the SHARED TTS interface.

    This endpoint used to construct `edge_tts` inline, with a Piper fallback
    guarded by two bare `except: pass` blocks -- so an operator could not tell a
    blocked proxy from a missing package from a bad voice name, and the Piper
    branch had never worked (its pinned version was not even installable; see
    docs/voice-known-issues.md VKI-3).

    The engine that produced the audio is returned in `X-TTS-Engine`. A caller
    that cannot tell which engine ran cannot report a degraded state, which is
    how VKI-1 was able to serve silence with a 200.
    """
    text = (payload or {}).get("text", "")
    if not text:
        raise HTTPException(400, "No text provided")
    try:
        audio, media_type, engine = await tts.synthesize(text[:1500],
                                                         getattr(user, "voice", None))
    except tts.TTSUnavailable as exc:
        raise HTTPException(501, str(exc))
    return Response(content=audio, media_type=media_type,
                    headers={"X-TTS-Engine": engine})


@router.get("/engines")
async def engines(user=Depends(get_current_user)):
    """Per-engine readiness. The surface that makes a weightless fallback
    visible instead of a runtime surprise -- see VKI-5."""
    return tts.engine_status()
