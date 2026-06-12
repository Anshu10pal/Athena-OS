"""Optional desktop wake-word listener — "Hey Athena" without touching the keyboard.

Runs OUTSIDE the web app as a small always-on script. When the wake word fires,
it records until silence, sends audio to the backend /api/voice/transcribe,
posts the text to /api/chat/stream, and plays the reply via /api/voice/speak.

Setup (separate phase — don't start here):
  pip install openwakeword sounddevice numpy requests
  python wake_word.py --token <your_jwt>

This is a Phase 4 feature; the web app's push-to-talk works without it.
"""
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="JWT from logging into ATHENA OS")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    try:
        import numpy as np  # noqa: F401
        import sounddevice as sd  # noqa: F401
        from openwakeword.model import Model  # noqa: F401
    except ImportError:
        print("Install deps first: pip install openwakeword sounddevice numpy requests")
        return

    print("TODO (Phase 4): wire openwakeword 'hey jarvis' model -> record -> /api/voice/transcribe -> /api/chat")
    print("Backend:", args.backend)


if __name__ == "__main__":
    main()
