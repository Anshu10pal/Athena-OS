"""Directory-level and cohort-level views of health scores that already exist.

Nothing here measures anything. Every number is a re-aggregation of the
per-file rows a snapshot already stored, which has three consequences worth
stating:

1. **No migration and no re-analysis.** These views work retroactively on
   every snapshot ever written, including ones taken before this module
   existed.
2. **They cannot drift from the scores they summarise**, because they are a
   pure function of those same rows rather than a parallel computation.
3. **The contract is untouched.** No threshold, weight or marker changes.
   `thresholds_version` is unaffected -- these are new views of old numbers,
   not new measurements.

The point of the directory view is that "your repo is 94" is not actionable
and "your services/codebase directory is 88 across 28 files" is.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import CodeFile, CodeFileHealth, CodeHealthSnapshot, Repo
from app.services.codebase.health_scoring import (
    ARCHITECTURE,
    CHANGE_HOTSPOT,
    MAINTAINABILITY,
)

ROLLUP_VERSION = 1

# A directory needs at least this many scored files before it is eligible to be
# RANKED as a weak spot. Every directory is still reported -- only the ranking
# is gated, because a directory holding one unusual file would otherwise top
# the list on a sample size of one. Same reasoning as the review-cost floor in
# effort-aware ranking: a ranking that ignores sample size manufactures
# priorities.
MIN_FILES_TO_RANK = 3

# Fraction of files, by commit count, that counts as "the code in motion".
HOT_COHORT_FRACTION = 0.10
# ...but never fewer than this many files, or the comparison is anecdote.
MIN_HOT_COHORT = 5

ROOT = "(root)"

# The axes this module aggregates, and which column each lives in. Change
# Hotspot is deliberately included: "which directory is churning" is a
# legitimate question even though the axis is uncalibrated, and it is reported
# as points on its own scale, never folded into the health axes.
AXIS_COLUMNS = {
    MAINTAINABILITY: "maintainability",
    ARCHITECTURE: "architecture_health",
    CHANGE_HOTSPOT: "change_hotspot_points",
}


def ancestors_of(path: str) -> list:
    """Every directory that contains this file, outermost first.

    `backend/app/api/repos.py` ->
        ["backend", "backend/app", "backend/app/api"]

    A file at the repo root belongs to the ROOT sentinel and nothing else. The
    full chain is used rather than the immediate parent alone because a file is
    genuinely the responsibility of every directory above it -- reporting only
    the leaf would mean `backend/` never has a score of its own, which is the
    level most readers actually ask about first.
    """
    if "/" not in path:
        return [ROOT]
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


@dataclass
class AxisRollup:
    """One axis aggregated over one set of files.

    Three summary numbers rather than one, because they answer different
    questions and a single figure would hide which of them is driving it:

    - `weighted_mean` -- weighted by NLOC. "If I open a random line of code
      here, how healthy is the file I land in." This is the headline.
    - `mean` -- unweighted. Diverges from the weighted mean exactly when one
      large file dominates, which is itself worth seeing.
    - `worst` (+ `worst_path`) -- the single file most worth opening.
    """

    files_scored: int = 0
    files_na: int = 0
    weighted_mean: Optional[float] = None
    mean: Optional[float] = None
    worst: Optional[float] = None
    worst_path: Optional[str] = None
    rankable: bool = False

    def as_dict(self) -> dict:
        return {
            "files_scored": self.files_scored,
            "files_na": self.files_na,
            "weighted_mean": self.weighted_mean,
            "mean": self.mean,
            "worst": self.worst,
            "worst_path": self.worst_path,
            "rankable": self.rankable,
        }


@dataclass
class DirectoryRollup:
    path: str
    depth: int
    files_total: int = 0
    nloc: int = 0
    axes: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "depth": self.depth,
            "files_total": self.files_total,
            "nloc": self.nloc,
            "axes": {k: v.as_dict() for k, v in self.axes.items()},
        }


def _aggregate_axis(rows: list, column: str, higher_is_worse: bool) -> AxisRollup:
    """Aggregate one axis over one set of rows.

    Files whose axis was N/A are counted separately and excluded from every
    average -- never coerced to 0 (which would read as "measured and terrible")
    and never to full marks (which would read as "measured and fine"). Same
    exclude-don't-zero rule the engine applies per marker; a rollup that broke
    it would undo the discipline one level up.
    """
    out = AxisRollup()
    scored = []
    for r in rows:
        value = getattr(r, column)
        if value is None:
            out.files_na += 1
        else:
            scored.append((value, max(r.nloc or 0, 0), r.path))

    out.files_scored = len(scored)
    if not scored:
        return out

    values = [v for v, _, _ in scored]
    out.mean = round(sum(values) / len(values), 3)

    total_weight = sum(w for _, w, _ in scored)
    if total_weight > 0:
        out.weighted_mean = round(sum(v * w for v, w, _ in scored) / total_weight, 3)
    else:
        # Every file has zero NLOC, so size-weighting has nothing to weigh.
        # Falling back to the unweighted mean is honest; inventing a weight
        # would not be.
        out.weighted_mean = out.mean

    worst_value, _, worst_path = (max if higher_is_worse else min)(scored, key=lambda t: t[0])
    out.worst = round(worst_value, 3)
    out.worst_path = worst_path
    out.rankable = out.files_scored >= MIN_FILES_TO_RANK
    return out


def directory_rollup(rows: list, max_depth: Optional[int] = None) -> list:
    """Per-directory aggregates over a snapshot's stored per-file rows.

    Returns every directory, outermost first then alphabetical. Callers rank
    and slice; this function does not decide what "worst" means for a UI.
    """
    buckets = defaultdict(list)
    for r in rows:
        for d in ancestors_of(r.path):
            depth = 0 if d == ROOT else d.count("/") + 1
            if max_depth is not None and depth > max_depth:
                continue
            buckets[d].append(r)

    out = []
    for path, group in buckets.items():
        depth = 0 if path == ROOT else path.count("/") + 1
        entry = DirectoryRollup(
            path=path,
            depth=depth,
            files_total=len(group),
            nloc=sum(r.nloc or 0 for r in group),
        )
        for axis, column in AXIS_COLUMNS.items():
            entry.axes[axis] = _aggregate_axis(
                group, column, higher_is_worse=(axis == CHANGE_HOTSPOT)
            )
        out.append(entry)

    out.sort(key=lambda e: (e.depth, e.path))
    return out


def weakest_directories(rollups: list, axis: str = MAINTAINABILITY, limit: int = 5) -> list:
    """Lowest-scoring directories, restricted to those with enough files to
    rank (see MIN_FILES_TO_RANK). Ties broken by size, so a larger weak
    directory outranks a smaller one at the same score."""
    eligible = [r for r in rollups
                if r.axes.get(axis) and r.axes[axis].rankable and r.axes[axis].weighted_mean is not None]
    higher_is_worse = axis == CHANGE_HOTSPOT
    eligible.sort(key=lambda r: (
        -r.axes[axis].weighted_mean if higher_is_worse else r.axes[axis].weighted_mean,
        -r.nloc,
    ))
    return eligible[:limit]


# ---------------- the code in motion ----------------


@dataclass
class HotCohort:
    """How the files you change most compare with the codebase overall.

    Deliberately compares MAINTAINABILITY, which takes no churn input at all
    (`complexity_under_churn` lives on the Change Hotspot axis, not this one).
    Comparing a churn-derived score against a churn-selected cohort would be
    circular, and a reader is right to suspect that, so the independence is
    stated in the payload rather than left to be trusted.
    """

    available: bool = False
    na_reason: Optional[str] = None
    hot_files: int = 0
    hot_mean: Optional[float] = None
    baseline_files: int = 0
    baseline_mean: Optional[float] = None
    delta: Optional[float] = None
    churn_threshold: Optional[int] = None
    caveat: Optional[str] = None
    paths: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "na_reason": self.na_reason,
            "hot_files": self.hot_files,
            "hot_mean": self.hot_mean,
            "baseline_files": self.baseline_files,
            "baseline_mean": self.baseline_mean,
            "delta": self.delta,
            "churn_threshold": self.churn_threshold,
            "caveat": self.caveat,
            "paths": self.paths,
            "axis": MAINTAINABILITY,
            "axis_note": (
                "Maintainability takes no change-history input, so this compares two "
                "independent measurements rather than a signal against itself."
            ),
        }


def _young_history_caveat(commit_counts: list) -> Optional[str]:
    """In a repository with little history, "changed most" overlaps heavily
    with "written most recently" -- the files you touched most are the ones you
    built last, not necessarily unstable ones. That confound disappears once a
    repo has years of history, and it belongs beside the number rather than in
    a document."""
    if not commit_counts:
        return None
    if max(commit_counts) <= 10:
        return (
            "This repository has little history (no file has more than "
            f"{max(commit_counts)} commits), so 'changed most' overlaps with "
            "'written most recently'. Read the gap as a hint, not a verdict."
        )
    return None


def hot_cohort(rows: list, commit_counts: dict) -> HotCohort:
    """Compare the highest-churn files against every scored file.

    `commit_counts` maps file_id -> commit_count (None where unknown).

    Gated on churn carrying information at all, using the same test the Change
    Hotspot axis uses: fewer than three distinct commit counts and the cohort
    is not a cohort, it is an arbitrary slice. On a shallow clone every file
    reports the same count, so "the files you change most" would silently mean
    "an alphabetical prefix of the repo".
    """
    out = HotCohort()

    scored = [r for r in rows if r.maintainability is not None]
    if not scored:
        out.na_reason = "No file has a Maintainability score in this snapshot."
        return out

    with_churn = [(r, commit_counts.get(r.file_id)) for r in scored]
    with_churn = [(r, c) for r, c in with_churn if c is not None]
    if not with_churn:
        out.na_reason = "No change history has been computed for this repo."
        return out

    counts = [c for _, c in with_churn]
    if len(set(counts)) < 3:
        out.na_reason = (
            f"Change frequency carries no information here -- only {len(set(counts))} "
            "distinct commit count(s) across the repo, typical of a shallow clone. "
            "Ranking by a constant would produce a confident-looking list with "
            "nothing behind it."
        )
        return out

    ordered = sorted(with_churn, key=lambda t: t[1], reverse=True)
    target = max(MIN_HOT_COHORT, int(round(len(ordered) * HOT_COHORT_FRACTION)))
    target = min(target, len(ordered))

    # Extend through the tie at the boundary rather than cutting mid-value:
    # two files with identical commit counts must not land on opposite sides of
    # the line purely because of sort order.
    threshold = ordered[target - 1][1]
    hot = [r for r, c in ordered if c >= threshold]
    if len(hot) == len(ordered):
        out.na_reason = (
            "Every file with history shares the top commit count, so there is no "
            "distinct 'most changed' cohort to compare."
        )
        return out

    baseline = [r for r, _ in with_churn]

    out.available = True
    out.churn_threshold = threshold
    out.hot_files = len(hot)
    out.hot_mean = round(sum(r.maintainability for r in hot) / len(hot), 3)
    out.baseline_files = len(baseline)
    out.baseline_mean = round(sum(r.maintainability for r in baseline) / len(baseline), 3)
    out.delta = round(out.hot_mean - out.baseline_mean, 3)
    out.caveat = _young_history_caveat(counts)
    out.paths = [r.path for r in sorted(hot, key=lambda r: r.maintainability)[:10]]
    return out


# ---------------- DB entry point ----------------


def build_rollup(db: Session, repo: Repo, snapshot: CodeHealthSnapshot,
                 max_depth: Optional[int] = None, weak_limit: int = 5) -> dict:
    """Everything the directory view needs, from stored rows only."""
    rows = (
        db.query(CodeFileHealth)
        .filter(CodeFileHealth.snapshot_id == snapshot.id)
        .all()
    )
    commit_counts = dict(
        db.query(CodeFile.id, CodeFile.commit_count)
        .filter(CodeFile.repo_id == repo.id)
        .all()
    )

    directories = directory_rollup(rows, max_depth=max_depth)
    return {
        "snapshot_id": snapshot.id,
        "rollup_version": ROLLUP_VERSION,
        "files_in_snapshot": len(rows),
        "min_files_to_rank": MIN_FILES_TO_RANK,
        "directories": [d.as_dict() for d in directories],
        "weakest": {
            axis: [d.path for d in weakest_directories(directories, axis=axis, limit=weak_limit)]
            for axis in AXIS_COLUMNS
        },
        "hot_cohort": hot_cohort(rows, commit_counts).as_dict(),
    }
