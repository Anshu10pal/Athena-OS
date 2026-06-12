"""Local voice endpoints — optional. Install with: pip install -r requirements-voice.txt

STT: faster-whisper (CPU int8). TTS: Piper. Both fully local and free.
If the packages aren't installed, these endpoints return 501 and the frontend
falls back to the browser's built-in speech APIs.
"""
import io
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.security import get_current_user

router = APIRouter(prefix="/api/voice", tags=["voice"])

_whisper_model = None


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user=Depends(get_current_user)):
    global _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(501, "Local STT not installed. Run: pip install -r requirements-voice.txt")
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
        import aiohttp
        import edge_tts
        import ssl

        voice_name = getattr(user, "voice", None) or "en-US-AriaNeural"
        # Corporate-proxy bypass: skip cert verification for the bing speech websocket
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)

        communicate = edge_tts.Communicate(text[:1500], voice=voice_name)
        buf = io.BytesIO()
        async with aiohttp.ClientSession(connector=connector) as session:
            communicate.session = session  # force edge-tts to reuse our patched session
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
        raise HTTPException(501, "No TTS available. Run: pip install edge-tts")
    import os
    import wave

    voice_path = os.environ.get("PIPER_VOICE", "voices/en_US-lessac-medium.onnx")
    if not os.path.exists(voice_path):
        raise HTTPException(501, "No TTS available. Run: pip install edge-tts")
    voice = PiperVoice.load(voice_path)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize(text, wav)
    return Response(content=buf.getvalue(), media_type="audio/wav")
