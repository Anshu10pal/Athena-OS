#!/usr/bin/env bash
# Fetch voice model weights for LOCAL development.
#
# Production does NOT use this: Phase 5 of the voice migration COPYs the same
# files into the Docker image at build time, which is what closes KI-2 and
# VKI-4 (a runtime model fetch hides a broken install and breaks behind the
# SSL-intercepting proxy). This script exists so a developer's checkout can
# reach the same state without a container build.
#
# No verify=False anywhere, and none needed: curl uses the system trust store.
# Behind a TLS-intercepting proxy, export CURL_CA_BUNDLE (or REQUESTS_CA_BUNDLE
# for the Python paths) pointing at the corporate CA bundle.
set -euo pipefail
cd "$(dirname "$0")/.."
MODELS="models"
KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

mkdir -p "$MODELS" "$MODELS/piper"

# Kokoro: int8, not fp32. int8 quantisation targets CPU inference and is 88 MB
# against fp32's 310 MB -- and it matches the compute_type="int8" this project
# already chose for faster-whisper.
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  if [ -f "$MODELS/$f" ]; then echo "have  $f"; else
    echo "fetch $f"; curl -fSL --retry 3 -o "$MODELS/$f" "$KOKORO_BASE/$f"; fi
done

# Piper fallback voice. NOT committed to git (60 MB, and git keeps a binary
# forever). Until this runs, the Piper engine reports itself broken via
# /api/voice/engines rather than pretending -- see VKI-5.
for f in en_US-lessac-medium.onnx en_US-lessac-medium.onnx.json; do
  if [ -f "$MODELS/piper/$f" ]; then echo "have  piper/$f"; else
    echo "fetch piper/$f"; curl -fSL --retry 3 -o "$MODELS/piper/$f" "$PIPER_BASE/$f"; fi
done

echo
echo "done. verify with:"
echo "  venv/bin/python -c \"import sys;sys.path.insert(0,'.');from app.services.voice import tts;import json;print(json.dumps(tts.engine_status(),indent=2))\""
