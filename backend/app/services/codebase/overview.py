"""Phase K1: aggregate stats + structural health for the repo overview page.

Read-only over what ingest/rank/clustering already persisted -- no
filesystem walk, no re-parse, no re-clustering (the H1.5 rule: a read
endpoint must not recompute what a write already stored).

## What "health" means here, and what it deliberately does NOT mean

This module computes a **structural health** score. Every factor is
something this project actually measures. None of it is defect
prediction, and the score must never be presented as such:

- There is no defect data anywhere in this system. No issue tracker
  linkage, no bug-fix commit classification, no post-release failure
  history. A "which files have the most bugs" number would have nothing
  real behind it.
- The nearest honest proxy is a change hotspot (a file that changes often
  AND is heavily depended on -- the Tornhill/Nagappan formulation).
  hotspots() below computes exactly that and is labelled as a risk proxy,
  not as measured defects.
- That proxy itself is only meaningful when churn has variance. On a
  shallow clone (`git clone --depth 1`) every file reports the same
  commit_count, so churn carries zero information -- verified directly on
  this project's own eslint validation repo, where all 398 files report
  commit_count == 1. churn_is_degenerate() detects that case and the
  caller reports it instead of ranking files by a constant.

Each factor is returned with its own value, weight, and a plain-language
note, because a single opaque number is exactly the thing this project's
own ESLint validation rounds argue against. The score is a weighted mean
of only the factors that are ACTUALLY AVAILABLE for this repo -- an
unavailable factor is dropped from both numerator and denominator rather
than being scored as zero, the same "exclude, don't count as agreement"
rule the clustering metrics use for unclustered files.
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import CodeFile, CodeImport, CodeSubsystem, CodeSymbol, Repo
from app.services.codebase.dir_aggregation import dirname_of

HOTSPOT_LIMIT = 10
# Path segments that mark a file as a test. Substring-matched against the
# POSIX path, matching how the rest of this codebase already identifies
# tests (dir_aggregation's kind assignment).
TEST_PATH_MARKERS = ("test_", "_test.", "/tests/", "/test/", ".test.", ".spec.", "__tests__")


def _pct(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator else 0.0


def counts(db: Session, repo: Repo) -> dict:
    """Raw size/shape of the repo. Every number here is a direct count of
    rows ingest wrote -- nothing derived, nothing estimated."""
    rid = repo.id
    files = db.query(CodeFile).filter(CodeFile.repo_id == rid)

    total_files = files.count()
    total_lines = db.query(func.sum(CodeFile.line_count)).filter(CodeFile.repo_id == rid).scalar() or 0
    total_bytes = db.query(func.sum(CodeFile.size_bytes)).filter(CodeFile.repo_id == rid).scalar() or 0

    languages = dict(
        db.query(CodeFile.language, func.count())
        .filter(CodeFile.repo_id == rid).group_by(CodeFile.language).all()
    )
    categories = dict(
        db.query(CodeFile.prior_category, func.count())
        .filter(CodeFile.repo_id == rid).group_by(CodeFile.prior_category).all()
    )
    # "Symbols", not "exports" -- the parser records every declared
    # class/function/method, and does NOT record whether a symbol is
    # exported. Calling these exports would overstate what was measured.
    symbol_kinds = dict(
        db.query(CodeSymbol.kind, func.count())
        .join(CodeFile, CodeSymbol.file_id == CodeFile.id)
        .filter(CodeFile.repo_id == rid).group_by(CodeSymbol.kind).all()
    )

    imports_total = db.query(CodeImport).filter(CodeImport.repo_id == rid).count()
    imports_resolved = (
        db.query(CodeImport).filter(CodeImport.repo_id == rid, CodeImport.resolved.is_(True)).count()
    )

    # "Modules" is not a stored concept -- reported as the count of
    # distinct immediate directories, which is what the architecture map
    # already treats as a module-level unit (dir_aggregation.dirname_of).
    paths = [p for (p,) in db.query(CodeFile.path).filter(CodeFile.repo_id == rid).all()]
    directories = len({dirname_of(p) for p in paths})
    test_files = sum(1 for p in paths if any(m in p for m in TEST_PATH_MARKERS))

    return {
        "files": total_files,
        "lines": int(total_lines),
        "bytes": int(total_bytes),
        "directories": directories,
        "test_files": test_files,
        "languages": languages,
        "categories": categories,
        "symbols_total": sum(symbol_kinds.values()),
        "symbol_kinds": symbol_kinds,
        "imports_total": imports_total,
        "imports_resolved": imports_resolved,
        "imports_unresolved": imports_total - imports_resolved,
        "import_resolution_rate": _pct(imports_resolved, imports_total),
    }


def churn_is_degenerate(db: Session, repo: Repo) -> bool:
    """True when commit_count carries no information -- every file reports
    the same value (the shallow-clone case), or no rank run has computed
    history at all. Checked rather than assumed, because ranking files by a
    constant produces a confident-looking list with nothing behind it."""
    distinct = (
        db.query(CodeFile.commit_count)
        .filter(CodeFile.repo_id == repo.id, CodeFile.commit_count.isnot(None))
        .distinct().count()
    )
    return distinct <= 1


def hotspots(db: Session, repo: Repo, limit: int = HOTSPOT_LIMIT) -> dict:
    """Files that change often AND are heavily depended on.

    This is a RISK PROXY, not measured defects -- see the module docstring.
    Score is the product of normalised churn and normalised fan-in, the
    standard hotspot formulation: either factor alone is unremarkable (a
    config file churns without mattering; a stable utility has high fan-in
    without being risky), the product is what identifies "changes a lot and
    a lot depends on it."

    Returns available=False, with a reason, rather than a meaningless
    ranking when churn has no variance."""
    if churn_is_degenerate(db, repo):
        return {
            "available": False,
            "reason": (
                "Every file in this repo reports the same commit count, so change frequency carries no "
                "information here -- typical of a shallow clone (git clone --depth 1). Ranking files by a "
                "constant would produce a confident-looking list with nothing behind it."
            ),
            "files": [],
        }

    rows = (
        db.query(CodeFile)
        .filter(CodeFile.repo_id == repo.id, CodeFile.commit_count.isnot(None), CodeFile.fan_in.isnot(None))
        .all()
    )
    if not rows:
        return {"available": False, "reason": "No rank run has computed change history for this repo yet.", "files": []}

    max_churn = max((f.commit_count or 0) for f in rows) or 1
    max_fan_in = max((f.fan_in or 0) for f in rows) or 1

    scored = []
    for f in rows:
        churn = (f.commit_count or 0) / max_churn
        fan_in = (f.fan_in or 0) / max_fan_in
        score = churn * fan_in
        if score <= 0:
            continue  # a zero on either axis is not a hotspot, it's a non-event
        scored.append({
            "file_id": f.id, "path": f.path, "score": round(score, 4),
            "commit_count": f.commit_count, "distinct_authors": f.distinct_authors,
            "fan_in": f.fan_in, "lines": f.line_count,
        })
    scored.sort(key=lambda r: (-r["score"], r["path"]))
    return {"available": True, "reason": None, "files": scored[:limit]}


def _factor(key: str, label: str, value: Optional[float], weight: float, detail: str,
            available: bool = True) -> dict:
    return {
        "key": key, "label": label, "weight": weight, "detail": detail,
        "available": available,
        "value": round(value, 4) if (available and value is not None) else None,
    }


def health(db: Session, repo: Repo, stats: dict) -> dict:
    """A 0-1 structural health score plus the factors that produced it.

    Explicitly NOT a defect predictor (module docstring). Every factor is
    normalised so that 1.0 is better; unavailable factors are excluded
    from the weighted mean entirely rather than counted as zero, so a repo
    that simply hasn't run clustering isn't penalised for it.
    """
    rid = repo.id
    factors = []

    # 1. Import resolution -- how much of the dependency graph the tool can
    #    actually see. Low resolution means every downstream number
    #    (ranking, clustering, this page) is built on a partial graph, so
    #    it belongs in a health readout even though it measures the
    #    ANALYSIS as much as the code.
    factors.append(_factor(
        "import_resolution", "Import resolution",
        stats["import_resolution_rate"], 0.25,
        f"{stats['imports_resolved']} of {stats['imports_total']} import statements resolved to a real file "
        f"in this repo. Unresolved imports are usually third-party packages, which is normal -- but the lower "
        f"this is, the more of the dependency graph is invisible to every other view.",
        available=stats["imports_total"] > 0,
    ))

    # 2. Documented symbols -- scored over PYTHON symbols only, and that
    #    restriction is a correctness fix, not a simplification. Only
    #    extract_python populates CodeSymbol.docstring; the JS/TS extractor
    #    never does, because JSDoc is a leading comment rather than a
    #    docstring node in the AST. Verified against real data, not
    #    assumed: 0 of 110 TS/TSX symbols carry a docstring on this
    #    project's own repo, and 0 of 1031 on the (heavily JSDoc'd) ESLint
    #    validation repo. Scoring those as "undocumented" would report a
    #    gap in THIS TOOL's parser as a deficiency in the code being
    #    analysed -- so a repo with no Python simply has this factor
    #    excluded from its score, per the exclude-don't-zero rule above.
    py_symbols = (
        db.query(CodeSymbol).join(CodeFile, CodeSymbol.file_id == CodeFile.id)
        .filter(CodeFile.repo_id == rid, CodeFile.language == "python")
    )
    py_total = py_symbols.count()
    py_documented = py_symbols.filter(
        CodeSymbol.docstring.isnot(None), CodeSymbol.docstring != ""
    ).count()
    factors.append(_factor(
        "documentation", "Documented symbols (Python)",
        _pct(py_documented, py_total), 0.15,
        (f"{py_documented} of {py_total} Python classes/functions/methods carry a docstring. "
         f"Python only -- this tool's JS/TS parser does not extract JSDoc, so scoring JS/TS symbols here "
         f"would measure the parser, not the code."
         if py_total else
         "No Python symbols in this repo. This tool only extracts docstrings from Python, so there is nothing "
         "to score -- excluded rather than counted as zero."),
        available=py_total > 0,
    ))

    # 3. Test presence -- a ratio of test files to source files, capped at
    #    1.0 where tests match or outnumber source. A crude proxy and
    #    labelled as one: it counts FILES, not coverage, and this project
    #    has no coverage data.
    source_files = max(stats["files"] - stats["test_files"], 1)
    factors.append(_factor(
        "test_presence", "Test presence",
        min(stats["test_files"] / source_files, 1.0), 0.2,
        f"{stats['test_files']} test files against {source_files} non-test files. This counts files, not "
        f"coverage -- no coverage data exists in this system, so a high score here means tests are present, "
        f"not that they test much.",
        available=stats["files"] > 0,
    ))

    # 4. Reachability -- files no entry point can reach. Already computed
    #    by compute_layers at rank time and persisted, so this is a read.
    ranked = db.query(CodeFile).filter(CodeFile.repo_id == rid, CodeFile.fan_in.isnot(None)).count()
    orphaned = db.query(CodeFile).filter(
        CodeFile.repo_id == rid, CodeFile.fan_in == 0, CodeFile.is_entry_point.isnot(True),
    ).count()
    factors.append(_factor(
        "connectedness", "Connectedness",
        1.0 - _pct(orphaned, ranked), 0.2,
        f"{orphaned} of {ranked} ranked files are imported by nothing and are not entry points. Some are "
        f"legitimately standalone (scripts, configs); a high count can also mean dead code, or imports this "
        f"tool could not resolve.",
        available=ranked > 0,
    ))

    # 5. Cycle freedom -- from the persisted cycle-coherence report, so it
    #    requires clustering to have run at least once.
    coherence = repo.subsystem_cycle_coherence
    cycles_available = isinstance(coherence, list)
    cycle_count = len(coherence) if cycles_available else 0
    directories = max(stats["directories"], 1)
    factors.append(_factor(
        "cycle_freedom", "Cycle freedom",
        (1.0 - min(cycle_count / directories, 1.0)) if cycles_available else None, 0.2,
        (f"{cycle_count} directory-level import cycles across {stats['directories']} directories."
         if cycles_available else
         "Requires a Dependency Clusters run -- not yet computed for this repo."),
        available=cycles_available,
    ))

    usable = [f for f in factors if f["available"] and f["value"] is not None]
    total_weight = sum(f["weight"] for f in usable)
    score = (sum(f["value"] * f["weight"] for f in usable) / total_weight) if total_weight else None

    return {
        "score": round(score, 4) if score is not None else None,
        "factors": factors,
        "factors_used": len(usable),
        "factors_total": len(factors),
        "caveat": (
            "Structural health only. This system has no defect data -- no issue tracker linkage, no bug-fix "
            "commit history -- so this is not a defect prediction and must not be read as one. It scores what "
            "is actually measured: how much of the import graph resolves, how much is documented and tested, "
            "how connected the graph is, and how many directory cycles exist."
        ),
    }


def build_overview(db: Session, repo: Repo) -> dict:
    stats = counts(db, repo)
    cluster_count = (
        db.query(CodeSubsystem)
        .filter(CodeSubsystem.repo_id == repo.id, CodeSubsystem.algorithm == "modularity")
        .count()
    )
    return {
        "repo": {
            "id": repo.id,
            "name": repo.name,
            "owner": repo.owner,
            "host": repo.host,
            "source_kind": repo.source_kind,
            "description": repo.description,
            "description_source": repo.description_source,
            "last_ingested_at": repo.last_ingested_at.isoformat() if repo.last_ingested_at else None,
            "last_ingested_sha": repo.last_ingested_sha,
            "reduced_confidence": repo.reduced_confidence,
        },
        "counts": stats,
        "cluster_count": cluster_count,
        "health": health(db, repo, stats),
        "hotspots": hotspots(db, repo),
    }
