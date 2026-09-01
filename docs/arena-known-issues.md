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

## Not filed here

The `verify=False` in `app/core/llm.py` is pre-existing, explicitly out of
scope, and deliberately not touched. Arena Phase A adds no new instance of it:
all Arena network egress goes through `app.core.llm`, and the module creates no
HTTP client of its own. Stated as a residual rather than hidden: this means
Arena Phase A cannot be validated against a real proxy independently of that
debt.
