# Voice stack — known issues

Defects found while auditing and migrating the voice stack. Filed at the point
of discovery, with the mechanism named, so they are not rediscovered later under
worse conditions.

Same discipline as `docs/arena-known-issues.md`: **name it, do not fix it under
the wrong task.** Each entry says which phase owns it.

---

## The Phase 1 baseline — what was broken before the migration

Recorded 2026-09-03, before any change, by booting the real `app.main` against
an isolated scratch database and calling every voice endpoint. Kept because
"here is what was broken" is only checkable if someone wrote it down while it
was still true.

| endpoint | before | after Phase 2 |
|---|---|---|
| `POST /api/voice/transcribe` | **501** "Local STT not installed. Run: pip install -r requirements-voice.txt" | **200** (empty transcript on a tone; correct) |
| `POST /api/oratory/analyze` | **501** "Local STT not installed. Run: pip install faster-whisper" | **400** "No speech detected" (correct for a tone) |
| `POST /api/voice/speak` | **501** "No TTS available. Run: pip install edge-tts" | **200** `audio/mpeg`, 11,952 B |
| `POST /api/communication/listening/passage` | **200** with `audio_b64: None`, `tts_unavailable: true` | **200** with audio present |
| `communication._synthesize()` | returned **0 bytes** | returned **11,952 bytes** |

The legacy `/interview` page is the third STT **call site**, not a third
endpoint — `InterviewArena.tsx:139` posts to `/api/voice/transcribe`.

Cause of all of it: the four voice packages lived in an OPTIONAL extras file
(`requirements-voice.txt`) that nothing installed, while three modules imported
them at request time. Closed in Phase 2 by merging them into
`requirements.txt`.

---

## VKI-1 — `listening/passage` degrades silently, and it is plausible rather than broken

**Owner: a Communication Gym task. NOT the voice migration.**

`app/api/communication.py:261-271` — `_synthesize` wraps the whole TTS call in a
bare `except Exception: return b""`. Its caller at `:291-302` then checks the
byte count and, when empty, returns **HTTP 200** with `tts_unavailable: true`
rather than an error.

Measured in the Phase 1 baseline: the endpoint took **2,456 ms**, spent one LLM
call generating the passage, returned 200, and produced **no audio at all**.

Why this is the §17.35 shape rather than a missing feature:

- The status code says success. A client that does not read the
  `tts_unavailable` flag renders a listening comprehension test with silence.
- The failure is swallowed at the point it happens. Nothing is logged — the
  bare `except` discards the exception object entirely, so an operator cannot
  tell a blocked proxy from a missing package from a malformed voice name.
- It cost a real LLM call before failing, so the quota was spent on an output
  nobody can use.

Minimum fix when the owning task reaches it: narrow the `except`, log the
exception with its type, and decide deliberately whether a listening test with
no audio is a 200 or a 503. Do not widen the handler.

---

## VKI-2 — the TTS fallback turns a listening test into a reading test, guarded only by a comment

**Owner: a Communication Gym task. NOT the voice migration.** Related to VKI-1
but a distinct defect: this one is about what the fallback *sends*, not about
how the failure is reported.

`app/api/communication.py:300-302`, verbatim:

```python
# Fallback: TTS blocked/unavailable -> hand the text to the client to read aloud via
# the browser speech synthesizer (the client must NOT render it on screen).
return {"audio_b64": None, "passage": passage, "questions": questions, ...}
```

Measured in the Phase 1 baseline: **673 characters of passage text were sent to
the client.**

The exercise is a *listening* comprehension test — the passage is deliberately
withheld in the success path, and the comment on the audio branch says so ("text
withheld so it's a genuine listening test", `:294`). In the fallback the same
text is handed over, and the only thing preventing the client from displaying it
is **a code comment addressed to the client author**. A comment is not an
access control. If the client renders it — or a future client does, or someone
opens devtools — the assessment silently becomes a reading test, and its scores
are no longer comparable to scores collected on the audio path.

This is not hypothetical in the other direction either: `Communication.tsx:411`
does read `data.passage` and feed it to `window.speechSynthesis`, so the field
is genuinely consumed today.

Minimum fix when the owning task reaches it: either do not send the passage at
all and fail the exercise honestly, or record on the attempt WHICH path served
it so audio-path and text-path scores are never pooled. The current state
pools them with nothing marking the difference.

---

## VKI-3 — `piper-tts==1.2.0` was never installable on this runtime

**RESOLVED in Phase 2** by bumping to `1.7.0`. Recorded because the mechanism
matters for how long it went unnoticed.

`piper-tts==1.2.0` requires `piper-phonemize~=1.1.0`, which publishes **no
distribution for Python 3.12** — every published version caps at `<3.12`, and
this project pins `python-3.12.8` in `runtime.txt`. So the Piper TTS fallback in
`voice.py` did not merely lack a voice file, as the audit reported: **its pinned
version could never have been installed here at all.**

It stayed invisible because the pin lived in an optional extras file nobody
installed. An unresolvable pin in a file that is never resolved produces no
error — the same shape as the rest of this document.

`1.7.0` dropped the `piper-phonemize` dependency entirely: it needs
`onnxruntime` (already present via fastembed) plus `pathvalidate`, so the
transitive graph is **smaller** than the broken pin's would have been.

**Carried forward to Phase 4:** the `synthesize()` API changed across
1.2.0 → 1.7.0, so the fallback call site at `voice.py:69-72`
(`voice.synthesize(text, wav)`) has not been verified against the installed
version and is very likely wrong. Reported rather than silently patched,
because the Piper fallback is Phase 4's subject.

---

## VKI-4 — the STT model still downloads at runtime

**Owner: Phase 5 of the voice migration.** Same defect class as
`docs/arena-known-issues.md` KI-2, now confirmed live for a second model.

Phase 2's probe caused faster-whisper to fetch its weights on first use:

```
~/.cache/huggingface/hub/models--Systran--faster-whisper-base    142 MB
```

`voice.py:52` and `oratory.py:65` both construct
`WhisperModel("base", device="cpu", compute_type="int8")`, which resolves the
model from HuggingFace on demand. Consequences are the ones KI-2 already
records for `bge-small-en-v1.5`: a cold Render container pays the download or
fails, and a fresh Windows checkout behind the SSL-intercepting proxy makes an
unauthenticated fetch that the proxy breaks.

Phase 5 bakes this, the Kokoro voice and the Piper voice into the image at build
time. Until then, voice works on this machine only because the cache is now
warm — which is exactly the condition that hid KI-2 for as long as it did.
