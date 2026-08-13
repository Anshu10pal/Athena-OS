"""Phase L: the findings queue -- health markers grouped into pickable work.

Why this is not a list of findings
----------------------------------
apache/superset produces 6,649 findings across 3,520 files. Listed per file,
81.4% of files carry exactly ONE finding even after the most aggressive cut, so
no per-file ordering discriminates: finding-count ties four fifths of the list
at 1, and adjusted exposure ties a fifth of it at 0. A list keyed on files is
not a queue, it is the file tree with annotations.

Rows are therefore keyed on (marker x directory) -- "cycle_participation in
superset/views, 40 files" is a piece of work someone can pick up, and a user
fixes a pattern in an area rather than one file at a time. The same aggregation
principle is already applied three times in this codebase: the architecture
map's directory rollup, Mermaid neighbour grouping, and collapsing singleton
clusters to one row.

Why the granularity is adaptive rather than a fixed depth
---------------------------------------------------------
Measured on snapshot 13 of apache/superset, at the queue's default cut:

    fixed level        rows    largest row
    top 1 segment        41    608 files
    top 2 segments      255    410 files
    top 3 segments      590    189 files
    full parent dir   1,335    122 files

**Row count and row size are inversely coupled, and no fixed level satisfies
both.** 41 rows is scannable but its top row is "cycle_participation in
superset", i.e. the entire backend, which is a true statement and useless as a
task. 1,335 rows have workable sizes and are no longer scannable. This is a
property of how source trees are shaped -- a few enormous directories and a
long tail of small ones -- not a tuning failure, and H1's directory rollup hit
the same wall and answered it the same way: roll up to a budget rather than
pick a depth.

So the split is adaptive. Start at the top segment; any row over
MAX_FILES_PER_ROW re-splits one level deeper, repeatedly, until rows fit or the
path runs out. Measured against the cap:

    cap    rows   largest row
    500      93           410
    200     109           189      <- default
    100     238           122
     50     439           122

200 is the knee. Below 100 the row count runs away while the largest row stops
shrinking, because some rows are *irreducible*: all 122 files of
`cycle_participation` in superset-ui-core live in one directory, and no cap
divides them. Those rows are MARKED rather than silently left oversized --
otherwise the next person tunes the cap trying to fix a row no cap fixes.

Irreducible rows are deliberately not split by a secondary key. Severity would
be the wrong one for the case that motivates it: cycle_participation's severity
derives from cycle size, so all members of one SCC score near-identically and
the split would be on a variable that barely varies. Subsystem cluster id is a
genuinely different partition, but fragmenting one SCC across cluster
boundaries presents a single architectural problem as several unrelated
smaller ones -- and clustering CONDENSED that cycle, so using its output to
divide the cycle back up inverts what it computed.

Why churn is a multiplier and not a row
---------------------------------------
`churn_volume` fires on 47.8% of evaluable files. Per section 17.11 a signal
that fires on half the corpus does not discriminate, and as queue rows it would
be 41% of the list while telling nobody which file to open. The deeper reason
is that churn is not a defect: "this file changes often" is a risk weight on
other findings. A complex method in a file nobody touches is less urgent than
the same method in a file changed weekly.

So churn leaves the findings list and enters the ordering weight, multiplying
rather than adding -- the same shape as F2's node priors, which are applied
multiplicatively post-PageRank precisely so a prior cannot be compensated for
by a strong signal elsewhere. It stays visible on the row so the information is
not lost.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Markers below this severity are hidden by DEFAULT, not dropped. The caller is
# expected to surface the hidden count -- 40.9% of raw findings sit at
# 0.01-0.24, which is noise in a work queue, but a silent filter is how someone
# concludes the tool missed something it simply did not show.
SEVERITY_FLOOR = 0.25

# The adaptive split budget. See the module docstring for the sweep this came
# from; 200 is the knee, not a round number.
MAX_FILES_PER_ROW = 200

# Promoted out of the findings list into the ordering weight.
CHURN_MARKER = "churn_volume"

# Guard on the split recursion. A path has finitely many segments so the loop
# terminates on its own; this bounds it against a pathological path rather than
# trusting that argument.
MAX_SPLIT_DEPTH = 24

AXES = ("maintainability", "architecture_health", "change_hotspot")


@dataclass(frozen=True)
class Finding:
    """One marker that fired on one file. A marker fires at most once per file,
    so a (marker, file) pair is unique and a row's finding count IS its file
    count -- they are never reported as separate columns."""

    path: str
    file_id: Optional[int]
    marker: str
    label: str
    severity: float
    exposure: float  # 0.0 when NULL -- see extract_findings
    churn: float     # 0.0..1.0, the churn_volume severity for this file


@dataclass
class QueueRow:
    marker: str
    label: str
    directory: str
    findings: list[Finding] = field(default_factory=list)
    irreducible: bool = False

    @property
    def file_count(self) -> int:
        return len(self.findings)

    @property
    def score(self) -> float:
        """severity x exposure x (1 + churn), summed over the row.

        Exposure multiplies rather than adds: a finding in a file nothing
        depends on and nobody changes contributes zero, which is the intended
        reading, not a missing value. Rows scoring zero sort last.
        """
        return sum(f.severity * f.exposure * (1.0 + f.churn) for f in self.findings)

    @property
    def peak_severity(self) -> float:
        return max((f.severity for f in self.findings), default=0.0)

    @property
    def churn_mean(self) -> float:
        """Mean churn severity across the row -- the visible churn indicator.
        Reported alongside the score rather than folded invisibly into it."""
        if not self.findings:
            return 0.0
        return sum(f.churn for f in self.findings) / len(self.findings)

    def to_dict(self) -> dict:
        """Row summary WITHOUT its files.

        Members are a separate request. Inline they cost 296 KB for
        apache/superset's 109 rows -- this product already carries one
        701 KB view and does not need a second -- while re-deriving one row's
        members costs 280 ms, nearly all of it the SQL read. Summaries alone are
        ~16 KB.
        """
        return {
            "marker": self.marker,
            "label": self.label,
            "directory": self.directory,
            "file_count": self.file_count,
            "score": round(self.score, 3),
            "peak_severity": round(self.peak_severity, 3),
            "churn_mean": round(self.churn_mean, 3),
            # True means "every file here shares one directory, so no cap
            # divides this row". Carried to the UI so an oversized row reads as
            # a stated property rather than a tuning failure.
            #
            # VERIFIED REACHABLE, but NOT at the default cap on apache/superset:
            # its one indivisible group is `cycle_participation` across 122
            # files in superset-ui-core, and 122 is under MAX_FILES_PER_ROW, so
            # the row is never split and never marked. Lowering the cap to 100
            # against real data produces exactly that row with irreducible=True.
            # So this flag is live and data-dependent -- any repo with more than
            # MAX_FILES_PER_ROW files of one marker in a single directory hits
            # it -- and it should not be mistaken for a flag that fires today.
            "irreducible": self.irreducible,
        }

    def files_payload(self) -> list[dict]:
        """Worst first, so expanding a row opens on the file that earned its
        place rather than on whatever path sorted first."""
        return [
            {"file_id": f.file_id, "path": f.path, "severity": round(f.severity, 3)}
            for f in sorted(self.findings, key=lambda f: (-f.severity, f.path))
        ]


def _dir_parts(path: str) -> list[str]:
    """Directory components of a file path, excluding the filename. A file at
    the repo root has none, and groups under "." rather than under its own
    filename -- which an earlier draft did, silently creating one row per
    root-level file."""
    return path.split("/")[:-1]


def _dir_key(path: str, level: int) -> str:
    return "/".join(_dir_parts(path)[:level]) or "."


def extract_findings(
    health_rows: Iterable[tuple[str, Optional[int], Optional[float], dict]],
    floor: float = SEVERITY_FLOOR,
) -> tuple[list[Finding], int, int]:
    """Pull fired markers out of stored explanation blobs.

    Takes (path, file_id, adjusted_exposure, explanation) so this stays free of
    the ORM and testable without a database.

    Returns (findings, hidden_below_floor, churn_files).

    Files whose axes were excluded -- the 782 under-10-line files on superset --
    carry NULL exposure and contribute no markers, so they fall out of both the
    numerator and the denominator here without a special case. That is
    exclude-don't-zero holding through the aggregation rather than being
    re-asserted at it.
    """
    churn_by_path: dict[str, float] = {}
    raw: list[tuple[str, Optional[int], Optional[float], str, str, float]] = []
    hidden = 0

    for path, file_id, exposure, explanation in health_rows:
        blob = explanation or {}
        for axis in AXES:
            for marker in (blob.get(axis) or {}).get("markers") or []:
                severity = marker.get("severity")
                if severity is None or severity <= 0:
                    continue
                key = marker.get("key") or "?"
                if key == CHURN_MARKER:
                    churn_by_path[path] = float(severity)
                    continue
                if severity < floor:
                    hidden += 1
                    continue
                raw.append((path, file_id, exposure, key, marker.get("label") or key,
                            float(severity)))

    findings = [
        Finding(
            path=path,
            file_id=file_id,
            marker=key,
            label=label,
            severity=severity,
            # NULL exposure means the hotspot axis was N/A for this file, not
            # that exposure is zero. It is coerced to 0.0 ONLY as a score
            # multiplier -- such a file cannot be ranked by a signal it does not
            # have, and ranking it last is the same answer as excluding it from
            # the ordering. It is never counted as a measured zero anywhere a
            # mean or a percentage is taken.
            exposure=float(exposure) if exposure is not None else 0.0,
            churn=churn_by_path.get(path, 0.0),
        )
        for path, file_id, exposure, key, label, severity in raw
    ]
    return findings, hidden, len(churn_by_path)


def build_rows(
    findings: list[Finding],
    max_files: int = MAX_FILES_PER_ROW,
) -> list[QueueRow]:
    """Adaptive (marker x directory) roll-up -- see the module docstring.

    Rows are returned sorted: score descending, then peak severity descending,
    then directory. The second and third keys matter because a row can score
    exactly zero (every file in it has no exposure), and without a deterministic
    tail the list reorders between renders for no visible reason.
    """
    if max_files < 1:
        raise ValueError(f"max_files must be at least 1, got {max_files}")

    # Seed at the top segment, then split only what exceeds the budget.
    pending: list[tuple[str, str, int, list[Finding]]] = []
    seeded: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        seeded[(f.marker, _dir_key(f.path, 1))].append(f)
    for (marker, directory), group in seeded.items():
        pending.append((marker, directory, 1, group))

    rows: list[QueueRow] = []
    while pending:
        marker, directory, level, group = pending.pop()

        if len(group) <= max_files or level >= MAX_SPLIT_DEPTH:
            rows.append(QueueRow(marker, group[0].label, directory, group))
            continue

        deeper: dict[str, list[Finding]] = defaultdict(list)
        for f in group:
            deeper[_dir_key(f.path, level + 1)].append(f)

        if len(deeper) <= 1:
            # Every file shares one directory: no depth divides this row. Kept
            # whole and marked, because it is TRUE -- 122 files in one cycle in
            # one package is the finding, and splitting it by a secondary key
            # would present one architectural problem as several unrelated ones.
            rows.append(QueueRow(marker, group[0].label, directory, group,
                                 irreducible=True))
            continue

        for sub_dir, sub_group in deeper.items():
            pending.append((marker, sub_dir, level + 1, sub_group))

    rows.sort(key=lambda r: (-r.score, -r.peak_severity, r.directory))
    return rows
