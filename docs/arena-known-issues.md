# Interview Arena — known issues raised in Phase 0, owned elsewhere

Two defects found while auditing for the Interview Arena that are **not Arena
bugs** and are **not being fixed in Arena Phase A**. Recorded here at the point
of discovery so they are not rediscovered under demo load, which is the
expensive time to find either of them.

Both were raised and accepted at the Phase 0 checkpoint, 2026-09-01.

---

## KI-1 — `app/core/llm.py` provider fallback cannot distinguish quota exhaustion from a transient error

**Owner phase: Voice Migration Phase 1 (instrumentation).** Filed there rather
than against Arena Phase 2 because *every* generation call in ATHENA rides on
this function — chat, roadmaps, modules, oratory, communication, cards and the
Arena alike. It is not an Arena problem that happens to affect others; it is a
shared-path problem the Arena happened to surface.

`chat()` and `chat_stream()` catch bare `Exception` per provider, log at
`warning`, and advance to the next provider:

```python
except Exception as e:  # rate limit / transient -> try next provider
    logger.warning("Provider %s failed (%s); falling back.", name, e)
    last_err = e
```

Three distinct failures are collapsed into one behaviour:

| Actual condition | What should happen | What happens |
|---|---|---|
| 429, retry-after a few seconds | back off, retry the SAME provider | permanently skips to the fallback for that call |
| Daily token/request quota exhausted | tell the user; the fallback will exhaust too | silently degrades to a single provider, then to `raise last_err` with no attribution |
| Transient network/5xx | retry, then fall back | falls back immediately |

Consequences, in order of how much they cost:

1. **No backoff and no first-provider retry.** A one-second rate-limit blip
   permanently moves that call to the slower/lower-quality provider.
2. **Quota exhaustion is invisible.** When Gemini's RPD is spent, every
   subsequent call silently runs on Groq at a different model and different
   quality, with nothing surfaced anywhere. The only symptom is that output
   quality changes — which reads as a prompt regression, not a quota event.
   This is the §17.35 shape: a platform default silently substitutes, and the
   result is plausible rather than broken.
3. **When both are exhausted, the error raised is the LAST provider's.** The
   first provider's failure — usually the informative one — is discarded, so
   the traceback names the wrong cause.

### ESCALATED 2026-09-02 — this stopped being theoretical and blocked the Arena acceptance run

The first real five-fixture acceptance run died on fixture five, and the failure
is this issue, exactly as described above:

- **Gemini** returned `429 — You exceeded your current quota` (daily RPD spent
  by the run itself: 4 fixtures x 3 runs x 2 calls = 24 successful calls, plus
  development).
- **Groq** returned `404 — The model llama-3.3-70b-versatile does not exist`.
  It has been **decommissioned**: the key lists 14 models and no `llama-3.3-*`
  chat model at all (see KI-4).
- **The traceback named GROQ.** For `fast=False` the order is
  `[gemini, groq]`, so `raise last_err` surfaced the LAST provider's error and
  discarded Gemini's — which was the informative one. Bullet 3 above,
  verbatim, on real data.

**And it defeated the mitigation built on top of it.** The acceptance protocol
discards and re-runs any rate-limited run rather than counting it as a failure
(`measure_repeated` / `_is_rate_limited` in
`scripts/arena_extraction_report.py`). That classifier inspected the raised
exception, saw Groq's `404 model_not_found`, correctly concluded "not a rate
limit", and raised instead of retrying. **A caller cannot classify a failure the
shared client attributes to the wrong provider**, so no amount of care at the
call site fixes this.

Consequence for sequencing: this is no longer only a Voice-Migration-Phase-1
instrumentation item. It is on the critical path of the Arena acceptance
measurement, and the measurement cannot be trusted to complete or to report its
own reason for not completing until the classification and attribution are
fixed.

Minimum fix when the owning phase reaches it: classify the exception (429 with
`retry-after` vs 429-quota vs other), retry the same provider with bounded
backoff on the first, and surface a distinguishable signal on the second. Do
NOT widen the `except`; narrow it.

**Constraint carried forward:** the fix must not introduce a new
`httpx.Client(verify=...)`. There is exactly one such client in this codebase
and it should stay exactly one.

---

## KI-2 — FastEmbed model weights are downloaded at runtime, not baked at build

**DECIDED 2026-09-01: pulled into Voice Migration Hard Constraint #2 ("bake any
model weights into the image at build time"). Not a recommendation — a decision.
Pre-warming was rejected.**

> **Cross-link for the Voice Migration workstream — read this if you are the one
> implementing Hard Constraint #2.**
>
> That constraint was written with the TTS weights in mind (Kokoro-82M, Piper).
> It now also covers **`BAAI/bge-small-en-v1.5`**, the FastEmbed ONNX embedding
> model, and the scope tightened for a reason that originated outside your
> workstream.
>
> **The Interview Arena is the trigger, not the sole beneficiary.** Arena Phase A
> puts embedding on the critical path of a user's *first* action — submitting a
> JD — where every prior consumer (chat memory, module search, subsystem
> clustering) tolerated a slow or failed first call. That moved an existing
> latent risk into a user-visible one, which is why the constraint is being
> tightened now rather than later. But `vector_store.py` and
> `codebase/embeddings.py` have both depended on this model since well before
> the Arena existed; baking it fixes them too.
>
> Concretely: whatever build step bakes the TTS weights should also populate the
> FastEmbed cache for `BAAI/bge-small-en-v1.5`. One model, ~80 MB, same step.

`app/services/vector_store.py`'s own docstring states the problem:

> First call downloads a small embedding model (~80 MB) automatically.

`BAAI/bge-small-en-v1.5` is fetched from HuggingFace on first use by both
`vector_store.client()` and `codebase/embeddings._get_model()`. This works on
the current dev machine only because the model is already in the local cache
from earlier use. It is a **deploy-time and fresh-machine risk, not a dev
risk** — which is why nothing has failed yet:

- **Render, cold container:** the first request that needs an embedding pays
  the download, or fails if egress is restricted. Arena Phase A makes this
  worse in kind, not degree: embedding is on the *critical path of the very
  first user action* (submitting a JD), where previously it was on chat memory
  and module search — both of which already tolerate a slow first call.
- **Windows dev, corporate SSL-intercepting proxy:** a fresh checkout's first
  embedding call is an unauthenticated HuggingFace fetch through the proxy.
  Constraint #6 exists precisely because this breaks.

**Why bake rather than pre-warm.** Pre-warming is a manual step performed
before a demo, and §17.33 is explicit that the same manual error three times
belongs in the tool rather than in someone's memory. A pre-warm that is
forgotten once, in front of an audience, costs more than the build-time change.
The Voice Migration phase already has "bake any model weights into the image at
build time" as a hard constraint and will already be baking Kokoro/Piper
weights; adding one 80 MB ONNX model to that step is marginal work there and a
standing hazard everywhere else.

**Interim, if a demo happens before that phase lands:** run one embedding call
against the target container/machine before the demo and confirm the cache
directory is populated. That is a mitigation, not a fix, and it should be
recorded as having been done manually.

---

## KI-3 — two files carry a whole-file CRLF conversion in the working tree

**Not an Arena problem and not in scope for this phase.** Filed so the next
person in this worktree sees the pattern named instead of rediscovering it.

`backend/app/db/models.py` and `frontend/src/lib/api.ts` are modified in the
working tree with **no content change at all** — `git diff --ignore-all-space`
shows only the Arena additions (199 and 74 lines). HEAD has zero CRLF lines;
the worktree copies have 1,088 and 737. Something — most plausibly a Windows
editor, given this project's dev environment — rewrote the line endings of both
files.

Consequence, and why it is worth a note: a plain `git add` on either file
commits that line-ending change and makes the diff read as a 1,200-line
rewrite, which destroys reviewability for whatever real change is in there.

**Mitigation used for the Arena commit** (repeatable):

```
# stage HEAD's bytes plus the appended lines, leaving the worktree untouched
git show HEAD:<path>            # -> head text
# blob = head text + the appended lines, LF throughout
git hash-object -w --stdin < blob
git update-index --cacheinfo 100644,<sha>,<path>
```

The Arena commit's diff for those two files is `198+/0-` and `73+/0-` as a
result, and the CRLF change stayed in the working tree where it was found.

**Real fix, out of Arena scope:** a `.gitattributes` at the repo root with
`* text=auto eol=lf`, which stops this recurring for everyone. It belongs to
whoever owns the editor doing it — the same person the other ~70 pre-existing
working-tree modifications belong to.

---

## Not filed here

The `verify=False` in `app/core/llm.py` is pre-existing, explicitly out of
scope, and deliberately not touched. Arena Phase A adds no new instance of it:
all Arena network egress goes through `app.core.llm`, and the module creates no
HTTP client of its own. Stated as a residual rather than hidden: this means
Arena Phase A cannot be validated against a real proxy independently of that
debt.

---

## KI-4 — RESOLVED 2026-09-03. `llama-3.3-70b-versatile` was decommissioned; replaced with `openai/gpt-oss-120b`

**Found 2026-09-02, during the Arena acceptance run. Affects the WHOLE
application, not the Arena. Not fixed here — the model choice is an app-wide
decision and `app/core/llm.py` is shared infrastructure.**

`app/core/llm.py` pins Groq to `llama-3.3-70b-versatile`. That model returns:

```
404 - The model `llama-3.3-70b-versatile` does not exist or you do not have access to it.
```

Confirmed against `GET /openai/v1/models` with the project's own key: **14
models available, and no `llama-3.3-*` chat model among them.** The chat-capable
ones are `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and
`openai/gpt-oss-safeguard-20b` (plus embedding/guard/whisper models).

**What this means, and why nobody noticed:**

- `FAST_ORDER` and `STREAM_ORDER` both put Groq FIRST. So every
  `chat(fast=True)` call — intent detection, scoring, oratory evaluation,
  communication grading, MCQ generation, the Arena's cluster naming — has been
  paying a failed round trip to Groq and silently falling through to Gemini.
- Which means **the application has effectively had ONE provider, not two, for
  however long the model has been gone.** The fallback that exists to survive a
  Gemini quota exhaustion was itself dead, so the first Gemini 429 is now a hard
  failure rather than a degradation.
- KI-1 is why this was invisible: a permanent `404 model_not_found` and a
  transient blip are handled identically, logged at `warning`, and never
  surfaced.

This is the §17.35 shape again — a platform default silently substituted (one
provider standing in for two) and the result was plausible rather than broken.

### Resolution

`app/core/llm.py` now pins Groq to **`openai/gpt-oss-120b`** — the closest
replacement in kind (large general-purpose, 131,072 context vs the old ~128k).

The candidate was qualified against what `llm.py` actually needs, not against
"does it respond", because a model failing any of these degrades **silently** to
Gemini — the same shape as KI-1:

| requirement | why it matters | result |
|---|---|---|
| non-empty `message.content` | `chat()` returns `content or ""` | pass |
| `response_format=json_object` | `chat_json` depends on it | pass |
| `stream=True` `delta.content` | `chat_stream` depends on it | pass 3/3 |
| non-empty content at `max_tokens=200` | `briefing.py:49` is a fast-lane call with a small cap, and a reasoning model can spend that budget thinking and return an empty string that propagates as SUCCESS | pass, 623-674 chars |

Verified through `llm.py` itself with the **Gemini key blanked**, so no fallback
could mask a fault.

**Rejected on measurement**, recorded so they are not retried blind:

- **`openai/gpt-oss-20b`** — yields **zero content deltas** when streaming.
  `chat_stream` would yield nothing and return, producing a silently empty chat
  reply.
- **`qwen/qwen3.6-27b`** — **leaks chain-of-thought into `content`**
  (`"<think>\nHere's a thinking process..."`, 163 output tokens to answer
  "capital of France"). `llm.py` would return the thinking as the answer.
- `groq/compound*`, `allam-2-7b`, `orpheus*`, `prompt-guard*`, `whisper*` —
  agentic systems, 4k-context Arabic, TTS and classifier models. Not general
  chat.

**Runner-up `qwen/qwen3.8-27b`** passed every check and is materially leaner:
0.24s vs 0.79s on a realistic JSON task, 56 vs 202 output tokens on the same
prompt. Against the measured **8,000 TPM** ceiling that token economy is a real
advantage, so it is the better choice **if the fast lane is ever split from the
streaming lane**. Not chosen now: one model serves both, and 27B would downgrade
the user-facing chat path.

**What this does NOT fix.** KI-1 stands. The fallback still cannot distinguish
quota exhaustion from a transient error, and still reports the last provider's
error rather than the informative one. What changes is that there is now a
second *working* provider behind Gemini, so a Gemini 429 degrades instead of
stopping — and per the Phase B note, Groq's leaky bucket degrades to a rate
rather than a cliff.

**Original decision framing, kept for the record:** which Groq model replaces
it, if any. The
free-tier candidates on this key are `openai/gpt-oss-120b` (larger, slower) and
`openai/gpt-oss-20b` (smaller, faster). Changing it alters behaviour for every
module that uses the fast lane, so it belongs to whoever owns
`app/core/llm.py` — not to Arena Phase A. Arena's only Groq dependency is the
cluster-naming call, which was moved to the fast lane deliberately and can be
moved back to Gemini in one line if the decision is to drop Groq entirely.

---

## Inherited from the Voice Migration — two items Arena owns

Both were discovered during the voice migration and are recorded in full in
`docs/voice-known-issues.md`. They are cross-referenced here because Arena, not
the migration, is where each forces a decision.

### VKI-7 — literal numeral matching against transcripts will produce false negatives

**Arena Phase B, rubric scoring.** Whisper renders spoken numbers under its own
normalisation rules: `"three fifteen"` came back as `"3 .15"` in the Phase 4
round-trip gate. Interview answers are dense with numerals — "port 8080", "the
90th percentile", "O(n log n)", "a 500 error" — and a scorer comparing a
transcript against literal expected tokens will mark correct answers wrong.

Relevant to Phase B's item scoring, which is exactly the rubric-versus-transcript
comparison this breaks. Not relevant to the Communication Gym's filler tally,
which matches word *categories* rather than literal strings.

### VKI-8 — Kokoro-on-CPU is not production-ready for interview-turn latency

**Arena voice, Phase B/C.** Measured: 5.5 s for one sentence, **62.5 s for a
673-character passage**. Projected to Arena question lengths that is 3–10 s of
TTS per turn — at the edge of a 2–4 s budget for the shortest questions,
outside it for anything longer, with no headroom for a follow-up probe.

The voice migration has now closed edge-tts as a liability (deleted in Phase 6,
2026-09-03); it does not deliver
real-time voice interviewing. Streaming synthesis, a smaller model, or an
accepted slower turn is a required design decision **before** Arena voice
ships.
