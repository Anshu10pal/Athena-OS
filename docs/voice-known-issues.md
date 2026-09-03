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

### Phase 6 status: PARTIALLY closed, and the distinction matters

**Do not read "voice works now" as "VKI-1 is fixed."** Two different things
happened and only one of them was a fix.

What changed is that the defect **no longer fires on the primary path**.
`_synthesize` previously returned `b""` because TTS was not installed at all, so
every listening passage served HTTP 200 with silence. TTS now works, so the
failure branch is not reached in normal operation.

What did **not** change is the code path. `app/api/communication.py::_synthesize`
still ends in `return b""`, `listening_passage` still branches on empty bytes,
and the endpoint still answers **200 with no audio** when synthesis fails. The
defect is dormant, not removed. Anything that breaks TTS — missing weights on a
fresh deploy, a Kokoro load failure with a weightless Piper behind it (see
VKI-5, now more likely) — puts the original behaviour straight back.

One correction to how this is often described, since the point of this note is
future readers: the `except` is **no longer bare**. Phase 4 gave it
`exc_info=True`, so a failure is now logged with its exception and an operator
can tell a blocked proxy from a missing package. That was half of VKI-1's
minimum fix, acquired for free by routing through the shared interface. The
remaining half — **200 versus 503** — is untouched and is what keeps this issue
open. Serving a 200 with no audio is the plausible-rather-than-broken shape;
the caller cannot detect it, and the frontend renders a listening exercise with
nothing to listen to.

**Still open. Closing it is a decision about the endpoint's contract, not a
voice-stack change**, which is why six phases of voice work correctly did not
close it.

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

---

## VKI-5 — the Piper fallback ships WITHOUT weights, by design and out loud

**Decided in Phase 4. Not a defect being tolerated — a documented state with a
self-test.**

The Piper voice file is **not committed**. `en_US-lessac-medium.onnx` is 60 MB,
and git keeps a binary forever even after it is deleted; Phase 5 COPYs the same
file into the Docker image at build time, so committing it would duplicate that
mechanism and add permanent repository weight for no gain.

The constraint that mattered here was "**silently** shipping a never-worked
fallback is not acceptable." So it is not silent:

- `tts.engine_status()` reports Piper as `ready: false` with the exact missing
  path and a pointer to this entry. Exposed at **`GET /api/voice/engines`**.
- `_synth_piper` raises `TTSUnavailable` naming the missing file and the fetch
  script, rather than returning empty bytes.
- `tests/test_voice_tts.py::test_piper_reports_broken_when_its_voice_file_is_absent`
  asserts it reports broken, so a future change that makes it *claim* health
  fails a test.

Measured state, **Phase 4, 2026-09-03 — SUPERSEDED, kept for provenance**:

```
GET /api/voice/engines
  configured: kokoro
  kokoro: ready
  piper : NOT ready — voice file missing at models/piper/en_US-lessac-medium.onnx
  edge  : ready (network-dependent)
```

Two things changed after that reading. Phase 5 taught
`scripts/fetch_models.sh` to fetch the Piper voice, so `piper` reports ready on
a machine that has run it; and Phase 6 deleted edge-tts, so the third row no
longer exists — `engine_status()` now returns exactly the two engines in
`ENGINE_ORDER`, both local.

**This raises VKI-5's cost rather than resolving it.** With edge-tts gone,
Piper is the ONLY fallback, so a checkout that has not fetched weights has
nothing behind Kokoro at all. The voice file is still not committed (60 MB, and
git keeps a binary forever). What prevents this being silent is that
`engine_status()` reports the unready state and
`tests/test_voice_bake.py::test_both_tts_engines_report_ready_with_egress_blocked`
fails if either engine is not genuinely ready offline.

To supply weights locally: `scripts/fetch_models.sh`. In production the build
command fetches them at build time (docs/DEPLOYMENT.md).

---

### Phase 6 escalation: same issue, higher consequence

**The issue did not change; what sits behind it did.** With edge-tts deleted,
Piper is the ONLY fallback.

    before Phase 6:  ships weightless, deployment must fetch
                     -> if the fetch fails, edge-tts still answers (over the network)
    after  Phase 6:  ships weightless, deployment must fetch
                     -> if the fetch fails, THERE IS NO FALLBACK AT ALL

That is a strictly worse failure mode reached by a strictly better decision, and
both halves are worth stating. Deleting the network engine was right — it is
what makes the offline guarantee real. The cost is that the local stack now has
no third leg, so a build whose fetch step fails silently produces a service
where Kokoro is the single point of failure for all speech.

What keeps this from being silent rather than merely bad:

- `engine_status()` reports the unready engine instead of claiming health, and
  `/api/voice/engines` exposes it.
- `scripts/fetch_models.sh` fetches the voice file with a pinned SHA256, so a
  corrupted or substituted download fails the build rather than the request.
- `tests/test_voice_bake.py::test_both_tts_engines_report_ready_with_egress_blocked`
  fails if **either** engine is not genuinely ready offline — it asserts set
  equality against `ENGINE_ORDER`, so a silently-dropped engine cannot pass it.

**Not fixed here.** The 60 MB voice file is still not committed, for the reason
it never was: git keeps a binary forever. What has changed is the price of the
build step failing, and that price is now recorded rather than inferred.

---

## VKI-6 — Chat and the legacy interview page received filler-stripped transcripts for an unknown period

**Owner: a data-quality question for whoever owns those surfaces. NOT the voice
migration, which has already fixed the cause.**

Until Phase 3, `/api/voice/transcribe` called Whisper with `vad_filter=True` and
no other options — so Whisper's default token suppression **deleted fillers**,
while `oratory.analyze` was configured verbatim and kept them. Two STT paths,
disagreeing about a hard requirement of this project.

`Chat.tsx` and `InterviewArena.tsx` (the legacy `/interview` page) both post to
`/api/voice/transcribe`. So every transcript either of those surfaces produced
was tidied, and any downstream artefact derived from one — a vault entry, a chat
memory embedding, an interview answer stored in `interview_sessions.transcript`
— carries filler-free text that does not represent how the user actually spoke.

**The cause is fixed** (Phase 3 routed both through the verbatim shared
service). What is NOT addressed:

- **How long.** The split predates the git history reviewed for this migration;
  no dated change introduced it.
- **What to do about existing rows.** They cannot be recovered — the audio was
  written to a tempfile and discarded. Any historical filler-rate or fluency
  comparison that mixes pre- and post-Phase-3 transcripts is comparing two
  different instruments, which is the §17.16 shape.

Minimum honest handling for the owning task: decide whether stored transcripts
need a provenance marker distinguishing pre- and post-fix capture, and do not
pool them in any longitudinal metric until that is settled.

---

## VKI-7 — numeral tokens survive Whisper round-trip only under NORMALISATION, not literally

**Owner: Interview Arena Phase B, rubric scoring specifically.** Not a voice
migration defect — a property of the transcription path that downstream
literal-token matching will trip over.

**Evidence, from the Phase 4 anchor pin.** Fixture text
`"The meeting starts at three fifteen on Thursday."` transcribed as
`"The meeting starts at 3 .15 on Thursday."` The transcript is *correct*; the
spoken number was rendered in digits. The pinned anchor `fifteen` was therefore
defeated by normalisation, not by a transcription failure.

**Why this matters where it is filed.** Interview answers to technical
questions are dense with numerals: "port 8080", "the 90th percentile", "O(n log
n)", "S3 bucket 3", "three nines of availability", "a 500 error". Whisper will
render each under its own normalisation rules — digits, or a mix — and none of
those forms is predictable from the spoken words. Any scorer that compares a
transcript against **literal expected tokens** will produce **false negatives**:
the candidate said the right thing and the rubric will not see it.

**Why the Communication Gym does not hit this.** Its filler tally operates on
word *categories* (`CORE_FILLERS`, `CRUTCH_CANDIDATES`, hedge phrase lists) via
a normaliser, not on literal-string equality against expected content. Category
membership is unaffected by whether "fifteen" is spelled or digitised.

**The reason to file it now rather than when it bites.** It surfaced only
because the anchors were pinned. Without that discipline it would have appeared
in Phase B's item scoring against real interview answers, where it would have
looked like *the extractor* or *the rubric* was broken rather than the
comparison method. This is the phase where the evidence exists, so it is the
phase that records it.

Minimum honest handling in Phase B: compare on a numeral-normalised form of
both sides, or score numerals via a range/semantic check rather than string
equality. Do NOT solve it by removing numerals from rubrics — the numbers are
often the answer.

---

### Phase 6 status: confirmed unchanged

One line, as the mechanism cannot change: the Phase 4 fixture still round-trips
through the Phase 5 offline-enforced stack — `test_voice_bake.py` transcribes
the committed Kokoro audio with egress blocked and the word-count-plus-anchor
gate still passes — and numeral normalisation is a property of Whisper's
decoder, untouched by where its weights are stored. VKI-7 stands exactly as
filed, against Arena Phase B.

---

## VKI-8 — Kokoro-on-CPU latency is not production-ready, and STREAMING WILL NOT FIX IT

**Owner: Interview Arena voice. Re-measured 2026-09-03 under the Phase 5
configuration; the conclusion got sharper and one of the three options I
originally listed is now ruled out.**

Measured offline, model already warm, so these are synthesis times and not load
times. Kokoro n=2, Piper n=3, median with (min, max); spreads are under 0.4 s,
so these are reproducible rather than single-shot.

| text | engine | synthesis | audio | **real-time factor** |
|---|---|---:|---:|---:|
| 673-char passage | kokoro | 70.35 s (70.21, 70.50) | 41.12 s | **1.71×** |
| 673-char passage | **piper** | **4.55 s** (4.51, 4.56) | 36.84 s | **0.12×** |
| 76-char question | kokoro | 9.07 s (9.06, 9.07) | 4.37 s | **2.07×** |
| 76-char question | **piper** | **1.38 s** (1.37, 1.38) | 3.65 s | **0.38×** |

**The number that matters is the real-time factor, not the seconds.** RTF > 1
means synthesis is *slower than playback*. At 1.7–2.1× Kokoro cannot generate
audio as fast as a listener consumes it.

**That rules out streaming synthesis as a standalone fix for Kokoro**, which was
the first of the three options originally filed here. Streaming converts total
latency into time-to-first-audio, and works only when the synthesiser stays
*ahead* of playback. At RTF 1.7 it falls behind immediately and stalls
mid-sentence — worse for a candidate mid-interview than a straightforward wait.
Recorded as a withdrawal rather than edited away: the original option list was
written from seconds alone, before RTF was measured.

**THE FINDING THAT CHANGES THIS ISSUE: Piper is 15× faster and already
installed.**

Measured while verifying the Phase 6 deletion, not sought out. Piper is the
existing fallback engine — same process, same onnxruntime, weights already
fetched by `scripts/fetch_models.sh` — and it synthesises the 673-char passage
in 4.55 s against Kokoro's 70.35 s, at RTF 0.12. It is roughly **eight times
faster than playback**, so it clears an interview-turn budget with enormous
headroom and streaming would genuinely work on top of it.

**This is not a recommendation to switch, and the measurement does not support
one.** Voice quality is why Kokoro was made primary in Phase 4, and quality was
NOT measured here — nothing in Phase 6 compared how the two engines sound. What
has changed is that the trade is now quantified on one side: the cost of
Kokoro's quality is 15× the synthesis time and an RTF that forbids streaming.
Whether that is worth paying is a product decision for the Arena voice phase,
and it now has a number attached instead of an intuition.

Phase 5 did not change Kokoro's latency and never claimed to — it closed a
*correctness* defect, not a performance one. The 62.5 s originally filed was the
whole `listening/passage` endpoint (LLM + TTS); TTS alone on 673 chars now
measures 70.35 s. Same order, no improvement.

*(Provenance note: two earlier drafts of this measurement mislabelled the
passage length — 466 and 580 characters both reported as 673. The numbers above
are from a run that asserts `len(passage) == 673` rather than trusting the
label. Kokoro's RTF came out at 1.70–1.71 at all three lengths, so the
conclusion never depended on the error, but the figures did.)*

**What remains open for Arena, revised:**

- **Measure onnxruntime intra-op thread count FIRST.** See VKI-9 — this is an
  hour of work that can invalidate everything below it, so it is not one option
  among several, it is the thing to do before choosing among them.
- **Switch the primary to Piper**, at a quality cost that has not been measured.
  Cheapest by far: no new dependency, no new weights, one env var. Blocked on a
  quality comparison nobody has run.
- **A faster Kokoro.** int8 is already the smallest published variant, so this
  means a different model rather than more quantisation.
- **Thread/session tuning, untested.** onnxruntime's default intra-op thread
  count may not be using the available cores; this is the cheapest thing to
  check and it has *not* been checked. Stated as a hypothesis with a named
  mechanism, not a finding.
- **Accepting a slower turn**, if the product can — an 8.5 s pause before each
  spoken question is a product decision, not a bug.
- **Streaming, only in combination with something that gets RTF below 1.** Not
  on its own.

A 72-char question costing 8.5 s sits well outside a 2–4 s interview-turn
budget. The projection originally filed here (3–10 s per turn) was right at its
upper bound.

---

## Phase 6 open item — the Render cross-check is still outstanding

**Not a Phase 5 residual; an open Phase 6 item.** The network-blocked assertion
is pinned locally (`tests/test_voice_bake.py`, zero connection attempts while
loading every model). What has *not* happened is confirmation in the real
environment: a Render deploy running the documented build command, then the
service loading models with no fetch in its network log.

Until that happens, the claim is "the code cannot fetch, verified locally" and
not "the deploy does not fetch, observed". Those are different claims and only
the first is currently supported. It lands whenever the next deploy does.

---

## VKI-9 — Kokoro's thread count has never been tuned, and it gates the Arena voice decision

**Filed as the CHEAPEST test available, and it must run before Arena voice
chooses between Kokoro and Piper.**

Every Kokoro latency figure in VKI-8 was measured at onnxruntime's default
intra-op thread count. Nobody set it. `onnxruntime` also reported only
`['AzureExecutionProvider', 'CPUExecutionProvider']` on this machine, so there
is no accelerator involved and thread count is the main lever left.

**The measurement:** Kokoro RTF on target hardware at intra-op threads of
**1, 2, 4, 8**, on the same 673-char passage and 76-char question VKI-8 pins,
n=3, median with (min, max) — the same protocol, so the numbers are comparable
to the ones already filed.

**Why it is high leverage rather than an optimisation chore.** VKI-8's central
conclusion is that Kokoro's RTF of 1.71 forbids streaming synthesis: the
synthesiser falls behind playback and stalls mid-utterance. That conclusion is
load-bearing for the whole Arena voice design.

> **If any thread configuration produces RTF < 1, streaming synthesis
> re-enters the design space and VKI-8's design implications change
> materially.**

A Kokoro that streams is a different engine, product-wise, from one that makes a
candidate wait 9 seconds before every question — and it would remove the reason
to consider trading voice quality for Piper's speed at all.

**Stated as a hypothesis with a named mechanism, not a finding.** The mechanism
is that ONNX matmul kernels parallelise across intra-op threads and the default
may not be using the available cores. It may also do nothing: quantised int8
kernels can be memory-bandwidth-bound, in which case more threads buy little.
Both outcomes are useful and neither is known today.

**Sequencing, and this is the point of filing it:** run this BEFORE the
Kokoro-vs-Piper decision, not after. Choosing an engine on numbers taken at an
untuned default risks trading away voice quality to solve a problem that a
configuration line already solved. One hour of work standing in front of a
decision that is expensive to reverse.

**Cost:** ~1 hour. **Blocks:** the Arena voice phase.
