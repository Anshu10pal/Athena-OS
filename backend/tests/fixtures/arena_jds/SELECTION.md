# How the three public fixtures were selected

Written BEFORE any posting was retrieved. The "vague" case is the one where
honest degradation versus dishonest degradation is the entire test, so if the
posting were chosen because it *felt* vague, the criterion would be measuring
the selector's intuition rather than the extractor's behaviour.

## Pre-declared operational definitions

**vague.txt** — a posting is vague when **fewer than 25% of its requirement
lines name a specific technology, tool, named methodology, or measurable
competency**. The remainder are non-specific personal attributes ("passion",
"self-starter", "team player", "wear many hats", "thrive in ambiguity",
"rockstar", "hungry"). The count and the ratio are recorded in the fixture
header, so the classification is checkable rather than asserted. First retrieved
posting meeting the threshold is used; postings are not screened for how the
extractor might behave on them.

**long.txt** — > 1500 words by `wc -w`. Preference for a posting with heavy
non-skill boilerplate (benefits, EEO statements, application procedure), because
that is the actual stress: whether `jd_sections` labels boilerplate correctly at
length, and whether the extractor stays out of it.

**short.txt** — < 200 words by `wc -w`, complete posting rather than a truncated
one. A posting cut down to fit would test truncation, not brevity.

## Sourcing constraints

- **No LinkedIn.** Terms-of-service problem, and scraped listings are not
  reachable in three months, which defeats the point of a reproducible fixture.
- Company career pages, government job boards, or `web.archive.org` snapshots.
- Provenance header on every file: source URL, retrieval date, and one line on
  why the posting represents its category.
- Committed **as of the retrieval date**. If the posting later disappears, the
  fixture and its header remain the record of what was measured.

## What must not happen to these files

The fragment filter's word list and the extraction prompt must NOT be tuned
against these three before the measurement run. That is the same
fixture-calibration failure (§17.27) already caught once in this phase, one step
removed. Extend after measurement, from what the run actually surfaces.
