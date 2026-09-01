"""Interview Arena: JD -> confirmed skill graph.

Phase A only. Item generation, question serving, scoring, Elo and reports are
later phases and deliberately absent -- there are no stub functions returning
defaults here, because a default score is indistinguishable from a real one and
that is precisely the defect card_grading.grade_llm_card exists to avoid.

Pipeline shape, and the reason it is shaped this way:

    jd_sections      deterministic   segment the JD into required/preferred/...
    jd_extract       1 LLM call      skill mentions, each with a verbatim span
    weighting        deterministic   5 signals -> weight + explanation
    canonicalise     deterministic   4-stage cascade -> one node per skill
    clustering       deterministic   agglomerative parents  (+1 LLM call to NAME)
    graph_build      orchestration   idempotent on (user, jd_hash, extractor)

Exactly two LLM calls, and neither of them decides anything structural. The
model reads prose and emits mentions; it names clusters it did not choose. Every
weight, tier, merge and grouping is computed in Python from the JD text, because
the requirement is to be able to explain a weight to someone who asks -- and a
number an LLM emitted has no derivation to offer.
"""
