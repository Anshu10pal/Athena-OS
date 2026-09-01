# Phase A acceptance fixtures

Five job descriptions, run by `scripts/arena_extraction_report.py`. Two are the
reviewer's own and are **held out**; three are public postings sourced for
structural stress.

## Provenance header is mandatory

Every `.txt` here carries a header above a `---` separator. Public postings
change and disappear, and an acceptance number measured against a document
nobody can retrieve is not reproducible — contract §17.16.

```
title: Senior Data Engineer
source: https://example.com/jobs/12345
retrieved: 2026-09-01
note: trimmed the application instructions; skills text is verbatim
---
<the job description text, verbatim from here down>
```

Only `title:` is read by the report script. The rest is for a human
reconstructing the run later.

## The five cases, and what each is for

| file | case | what it stresses |
|---|---|---|
| `foundry-fde.txt` | reviewer's current role (**held out**) | extraction accuracy on a domain the reviewer can grade precisely |
| `target-role.txt` | role the reviewer is learning toward (**held out**) | accuracy where the reviewer is *not* expert — the harder judgement |
| `vague.txt` | buzzwords, little substance | **honest vs dishonest degradation.** Few nodes, low confidence = PASS. Eight confident invented parents = HARD FAIL, precisely because it clears the structural bar |
| `long.txt` | >1500 words | truncation, boilerplate rejection, latency, section detection at length |
| `short.txt` | <200 words | the node budget. 2–4 parents here is a **PASS**, reported as such |

## Do not iterate the extractor against the two held-out files

They are the validation set. The reference pair-set that designed the
canonicalisation cascade is already spent as a validation instrument (it now
lives in `tests/test_arena_canonicalise.py` as a regression pin-set). Tuning
against these and then reporting a score on them would be the same failure one
step removed — §17.27.

## This is not run in CI

Each fixture costs two live model calls against a free tier with a low daily
request ceiling. `scripts/arena_extraction_report.py` is invoked by hand.
