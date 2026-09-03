#!/usr/bin/env bash
# Fetch EVERY model weight this application needs, at BUILD time.
#
# Renamed from fetch_voice_models.sh: it no longer fetches only voice models.
# Closing KI-2 required bringing FastEmbed's bge-small-en-v1.5 under the same
# step, so the old name had become wrong.
#
# WHY BUILD TIME AND NOT AN IMAGE LAYER. The original instruction said "bake
# weights into the Docker image". THERE IS NO DOCKER IMAGE -- docs/DEPLOYMENT.md
# states the project deliberately avoids Docker dependence, and the service runs
# on a Render buildpack (build: pip install -r requirements.txt; start:
# uvicorn). That premise went unverified across four filed items before an
# execution attempt caught it; see decisions.md, the unresolved-premise class.
#
# The buildpack equivalent is this script, run FROM the build command. The
# defect KI-2/VKI-4 describes is a RUNTIME fetch -- a user's first request
# pulling 316 MB. A build-time fetch is not that: it fails at build, loudly, on
# a deterministic schedule, and the build already requires ~1 GB of network
# egress for pip. It adds no new class of failure.
#
# WHY PROJECT-RELATIVE PATHS. Render's docs confirm the build filesystem carries
# into the runtime (it must -- pip installs at build and uvicorn runs at start)
# and that the runtime filesystem is otherwise ephemeral. What they do NOT
# document is whether build-time writes OUTSIDE the project directory (~/.cache,
# /tmp) reach the runtime. Betting the closure of these two defects on an
# undocumented behaviour would be the very class of defect they describe, so
# everything lands under backend/models/.
#
# WHY CHECKSUMS ARE NOT OPTIONAL. A pinned URL gives reproducibility only until
# the contents behind it change, which happens. An unverified fetch would
# succeed and produce a different runtime than yesterday's build, silently. A
# mismatch here fails the BUILD -- which is the whole point of moving the fetch
# to a deterministic time.
#
# NO verify=False, and none needed: curl uses the system trust store. Behind a
# TLS-intercepting proxy, export CURL_CA_BUNDLE / REQUESTS_CA_BUNDLE pointing at
# the corporate CA bundle.
set -euo pipefail
cd "$(dirname "$0")/.."
MODELS="${MODELS_DIR:-models}"
# Bare `python` is correct on Render's buildpack, which activates its own
# interpreter for the build command. Locally the venv is not on PATH, so this is
# overridable: PYTHON=venv/bin/python bash scripts/fetch_models.sh
PYTHON="${PYTHON:-python}"
mkdir -p "$MODELS" "$MODELS/piper" "$MODELS/whisper" "$MODELS/fastembed"

KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

# artifact|url|sha256   -- retrieved and verified 2026-09-03
ARTIFACTS=(
  "kokoro-v1.0.int8.onnx|$KOKORO_BASE/kokoro-v1.0.int8.onnx|6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"
  "voices-v1.0.bin|$KOKORO_BASE/voices-v1.0.bin|bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
  "piper/en_US-lessac-medium.onnx|$PIPER_BASE/en_US-lessac-medium.onnx|5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"
  "piper/en_US-lessac-medium.onnx.json|$PIPER_BASE/en_US-lessac-medium.onnx.json|efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"
)

fail() { echo "FATAL: $*" >&2; exit 1; }

for entry in "${ARTIFACTS[@]}"; do
  IFS='|' read -r rel url want <<< "$entry"
  dest="$MODELS/$rel"
  if [ -f "$dest" ]; then
    got=$(sha256sum "$dest" | awk '{print $1}')
    if [ "$got" = "$want" ]; then echo "ok    $rel"; continue; fi
    echo "stale $rel (checksum differs) -- refetching"
  fi
  echo "fetch $rel"
  curl -fSL --retry 3 --retry-delay 2 -o "$dest.part" "$url" \
    || fail "download failed for $rel from $url"
  got=$(sha256sum "$dest.part" | awk '{print $1}')
  # Verified BEFORE the artifact is moved into place, so a mismatched file is
  # never visible to the rest of the build under its real name.
  [ "$got" = "$want" ] || { rm -f "$dest.part"; fail \
    "CHECKSUM MISMATCH for $rel
  expected $want
  got      $got
  The contents behind the pinned URL changed. Do NOT update the expected sum to
  match without establishing what changed and why -- that turns this guard into
  a rubber stamp."; }
  mv "$dest.part" "$dest"
  echo "ok    $rel (verified)"
done

# faster-whisper and FastEmbed resolve their own weights from HuggingFace, so
# they are warmed through their own loaders rather than by curl. MODELS_OFFLINE
# is forced off for exactly this step -- it is the one moment a fetch is
# intended. Everywhere else it defaults to on, which makes a runtime fetch
# impossible rather than merely unnecessary.
echo "warm  faster-whisper base -> $MODELS/whisper"
MODELS_OFFLINE=0 "$PYTHON" -c "
from faster_whisper import WhisperModel
WhisperModel('base', device='cpu', compute_type='int8',
             download_root='$MODELS/whisper', local_files_only=False)
print('    faster-whisper cached')
"
echo "warm  bge-small-en-v1.5 -> $MODELS/fastembed   (this is KI-2)"
MODELS_OFFLINE=0 "$PYTHON" -c "
from fastembed import TextEmbedding
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='$MODELS/fastembed',
              local_files_only=False)
print('    fastembed cached')
"

echo
echo "all model weights present and verified under $MODELS/"
du -sh "$MODELS" 2>/dev/null || true
