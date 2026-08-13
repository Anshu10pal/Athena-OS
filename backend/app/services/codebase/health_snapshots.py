"""Phase 1 code health: snapshot writes.

**Atomic by construction.** A snapshot is a claim that "at revision X, under
scoring definition Y, these were the results" -- a half-written one is worse
than none, because a trend line cannot tell an incomplete run from a real
improvement. So:

- Every axis for every file is scored **in memory first**. Nothing touches the
  database until the whole run has succeeded.
- The snapshot row and all its per-file rows are written in **one
  transaction**, rolled back together on any failure.
- The snapshot is created **only on success**. There is no "in progress" or
  "partial" snapshot state to reason about, because none can exist.

Source identity, scoring versions, all axis results and their explanations
come from **the same run** -- a snapshot never mixes a fresh AST pass with a
stale graph or a different threshold version, because they are gathered once
and written together.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import CodeFile, CodeFileHealth, CodeHealthSnapshot, Repo
from app.services.codebase import git_ops
from app.services.codebase.ast_metrics import ANALYZER_VERSION, metrics_for
from app.services.codebase.health_scoring import (
    ARCHITECTURE,
    CATEGORY_CAPS,
    MARKER_NOT_APPLICABLE,
    MARKER_NO_INPUT,
    MARKER_ZERO_SEVERITY,
    CHANGE_HOTSPOT,
    MAINTAINABILITY,
    THRESHOLDS_VERSION,
    WEIGHTS_VERSION,
    AxisResult,
    FileInputs,
    adjusted_exposure,
    build_repo_context,
    percentile,
    score_file,
)

AXES = (MAINTAINABILITY, ARCHITECTURE, CHANGE_HOTSPOT)


def working_tree_dirty(local_path: str) -> Optional[bool]:
    """Whether uncommitted changes exist in the analysed tree.

    Load-bearing, not bookkeeping: for a `local` repo we analyse the user's
    live working directory, so HEAD may not describe the bytes measured at
    all. A snapshot recording a SHA while the tree was dirty would be a false
    provenance claim, and a trend built on those is meaningless.

    None means "could not determine" (no git binary, not a work tree) -- which
    is deliberately distinct from False.
    """
    if not git_ops.GIT_AVAILABLE:
        return None
    result = git_ops.run_git(["status", "--porcelain"], cwd=local_path)
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def source_fingerprint(db: Session, repo: Repo) -> str:
    """A manifest digest over the CONTENT that was actually analysed.

    `head_sha` + `working_tree_dirty` cannot identify a local working tree:
    two different sets of uncommitted edits share the same HEAD and the same
    `dirty = True`, so an idempotency check built on those alone would treat
    genuinely different source states as identical and skip a snapshot that
    should have been taken -- or worse, present an old snapshot as describing
    new code.

    Built from `CodeFile.content_sha256`, which ingest already computes per
    file, so this costs one indexed query and no re-hashing. Path is included
    alongside the hash so that a pure rename -- same content, different
    location -- still changes the fingerprint, since it changes the import
    graph and therefore the architecture axis.
    """
    rows = (
        db.query(CodeFile.path, CodeFile.content_sha256)
        .filter(CodeFile.repo_id == repo.id)
        .order_by(CodeFile.path.asc())
        .all()
    )
    digest = hashlib.sha256()
    for path, sha in rows:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((sha or "").encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def snapshot_staleness(db: Session, repo: Repo, snapshot: CodeHealthSnapshot) -> dict:
    """Does this stored snapshot still describe the repo as it is now?

    A read endpoint that returns the newest snapshot unconditionally will
    happily show a green 97 beside a repo whose files have since been removed
    -- observed in production, where the Contents panel read 0 files while the
    health tiles still showed the scores from a previous ingest. The snapshot
    was not wrong when it was taken; presenting it as current is what is
    wrong, and a caveat the reader has to go looking for is not enough when
    the number itself is the thing on screen.

    Uses the same content fingerprint the write path uses (one indexed query,
    no re-hashing), so "unchanged" here means exactly what it means there.
    """
    current_files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).count()
    if current_files == 0:
        return {
            "stale": True,
            "reason": "no_files_ingested",
            "detail": (
                "This repo currently has no ingested files, so this snapshot describes "
                "source that is no longer present. Re-run analysis to score what is there now."
            ),
        }
    if (snapshot.analyzer_version, snapshot.thresholds_version, snapshot.weights_version) != (
        ANALYZER_VERSION, THRESHOLDS_VERSION, WEIGHTS_VERSION
    ):
        return {
            "stale": True,
            "reason": "scoring_changed",
            "detail": (
                "The scoring definition has changed since this snapshot was taken "
                f"(analyzer {snapshot.analyzer_version}->{ANALYZER_VERSION}, "
                f"thresholds {snapshot.thresholds_version}->{THRESHOLDS_VERSION}, "
                f"weights {snapshot.weights_version}->{WEIGHTS_VERSION}). "
                "The numbers are not comparable to a fresh run."
            ),
        }
    if snapshot.source_fingerprint and snapshot.source_fingerprint != source_fingerprint(db, repo):
        return {
            "stale": True,
            "reason": "source_changed",
            "detail": (
                "The analysed files have changed since this snapshot was taken. "
                "Re-run analysis to score the current source."
            ),
        }
    return {"stale": False, "reason": None, "detail": None}


@dataclass
class SnapshotDecision:
    should_create: bool
    reason: str
    fingerprint: str


def should_create_snapshot(db: Session, repo: Repo) -> SnapshotDecision:
    """Whether the analysed source state or the scoring definition has changed
    since the last snapshot.

    Deliberately compares the CONTENT fingerprint and all three version
    stamps, not the SHA: re-running against an unchanged working tree should
    produce no new snapshot (otherwise an automatic pipeline manufactures
    duplicate rows and a trend line fills with meaningless identical points),
    while any real edit -- committed or not -- must produce one.
    """
    fingerprint = source_fingerprint(db, repo)
    latest = (
        db.query(CodeHealthSnapshot)
        .filter(CodeHealthSnapshot.repo_id == repo.id)
        .order_by(CodeHealthSnapshot.computed_at.desc(), CodeHealthSnapshot.id.desc())
        .first()
    )
    if latest is None:
        return SnapshotDecision(True, "No previous snapshot for this repo.", fingerprint)
    if latest.source_fingerprint != fingerprint:
        return SnapshotDecision(True, "Analysed source content changed.", fingerprint)
    if (latest.analyzer_version, latest.thresholds_version, latest.weights_version) != (
        ANALYZER_VERSION, THRESHOLDS_VERSION, WEIGHTS_VERSION
    ):
        return SnapshotDecision(True, "Analyzer or scoring version changed.", fingerprint)
    return SnapshotDecision(
        False,
        "Source content and scoring versions are unchanged since the last snapshot.",
        fingerprint,
    )


def _repo_root(repo: Repo) -> Path:
    root = Path(repo.local_path)
    return root / repo.source_root if repo.source_root else root


def collect_inputs(db: Session, repo: Repo, on_progress=None) -> list:
    """One AST pass over the repo's files, joined to already-persisted graph
    and history facts. Read-only.

    `on_progress(stage, current, total, message)` is optional and defaults to
    silence, so every existing caller and test is unaffected. It exists because
    this loop is where the health stage spends nearly all its time -- a full
    tree-sitter parse per file, independent of what changed, so its cost tracks
    repo size rather than diff size. On apache/superset that was 35.5s behind a
    single unchanging "Computing code health" message, the longest silent
    stretch in the whole pipeline.
    """
    root = _repo_root(repo)
    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    total = len(files)
    inputs = []
    for index, f in enumerate(files, 1):
        if on_progress is not None and index % 200 == 0:
            on_progress("health", index, total, "Computing code health")
        try:
            data = (root / f.path).read_bytes()
        except OSError:
            continue
        m = metrics_for(data, f.language)
        inputs.append(FileInputs(
            file_id=f.id, path=f.path, language=f.language,
            nloc=m.nloc if m else f.line_count,
            ast_available=m is not None,
            function_count=m.function_count if m else 0,
            max_cyclomatic=m.max_cyclomatic if m else None,
            max_nesting=m.max_nesting if m else None,
            max_conditional_operands=m.max_conditional_operands if m else None,
            max_function_nloc=m.max_function_nloc if m else None,
            broad_handler_count=m.broad_handler_count if m else None,
            graph_available=f.fan_in is not None and f.fan_out is not None,
            fan_in=f.fan_in, fan_out=f.fan_out, cycle_size=f.scc_size,
            commit_count=f.commit_count,
        ))
    return inputs


def _explain_axis(axis: AxisResult) -> dict:
    """The per-marker record stored WITH the snapshot. Stored rather than
    recomputed on read: a historical score that can only be explained by
    today's thresholds is not auditable, and re-deriving it would silently
    rewrite what the score meant at the time."""
    return {
        "available": axis.available,
        "na_reason": axis.na_reason,
        "direction": axis.direction,
        "inputs_complete": axis.inputs_complete,
        "missing_inputs": axis.missing_inputs,
        "provisional_value": axis.provisional_value,
        "resolution_limited": axis.resolution_limited,
        "resolution_note": axis.resolution_note,
        "total_deduction": round(axis.total_deduction, 4),
        "categories_capped": axis.categories_capped,
        "axis_capped": axis.axis_capped,
        "markers": [
            {
                "key": m.key, "label": m.label, "category": m.category,
                "available": m.available, "na_reason": m.na_reason,
                # Stored per marker so a historical explanation can still
                # distinguish "found nothing" from "never computed".
                "state": m.state,
                "raw_value": m.raw_value, "severity": m.severity,
                "deduction": round(m.deduction, 4),
                "effective_warn": m.effective_warn,
                "effective_saturate": m.effective_saturate,
            }
            for m in axis.markers
        ],
    }


def architecture_coverage(inputs: list, results: list, repo: Repo) -> dict:
    """The structured coverage disclosure for Architecture Health.

    Emitted as DATA, not left to the UI to remember: a high score on a narrow
    contract still reads as "the architecture is healthy", especially to a
    user who has just seen directory-level cycles elsewhere in this same
    product. Shipping the counts and limitations in the payload means a
    future UI cannot receive a score without also receiving the scope it
    applies to, and an API test can enforce that pairing.

    `directory_cycle_count` deliberately sits next to `file_level_cycle_count`
    even though only the latter is scored -- the two facts are not in
    conflict (a directory cycle needs only a1->b1 and b2->a2, with no file in
    a cycle), and showing them apart is what makes that legible instead of
    looking like a contradiction.
    """
    scc_sizes = {}
    for f in inputs:
        if f.cycle_size is not None and f.cycle_size > 1:
            scc_sizes[f.file_id] = f.cycle_size
    file_level_cycles = len({s for s in scc_sizes.values()})

    coherence = repo.subsystem_cycle_coherence
    directory_cycle_count = len(coherence) if isinstance(coherence, list) else None

    # "Active" means a marker actually CARRIED the score -- it fired on at
    # least one file -- not merely that it had data. A marker with complete
    # data that found nothing (file-level cycles here) contributed exactly
    # zero, and listing it as active would imply the score reflects a check
    # that in practice never engaged.
    # Per-marker state across the repo, resolved by precedence: a marker that
    # fired anywhere is active; otherwise its state is the strongest reason
    # it did not. Deliberately NOT one undifferentiated "inactive" list --
    # "never computed", "computed and found nothing", and "cannot apply here"
    # license completely different conclusions about coverage, and are easy to
    # conflate once flattened.
    fired, zero_severity, no_input, not_applicable = set(), set(), set(), set()
    for r in results:
        if not r.available:
            continue
        for m in r.markers:
            state = m.state
            if state == "fired":
                fired.add(m.key)
            elif state == MARKER_ZERO_SEVERITY:
                zero_severity.add(m.key)
            elif state == MARKER_NOT_APPLICABLE:
                not_applicable.add(m.key)
            else:
                no_input.add(m.key)

    active = sorted(fired)
    inactive = []
    for key in sorted((zero_severity | no_input | not_applicable) - fired):
        if key in zero_severity:
            state, detail = MARKER_ZERO_SEVERITY, "Measured across this repo and found nothing."
        elif key in no_input:
            state, detail = MARKER_NO_INPUT, "Its input was never computed for this repo."
        else:
            state, detail = MARKER_NOT_APPLICABLE, "Does not apply to the files in this repo."
        inactive.append({"key": key, "state": state, "detail": detail})

    limitations = [
        "Static import analysis only. Dynamic imports, reflection, plugin "
        "registries and generated code are not visible to it.",
    ]
    if directory_cycle_count:
        limitations.append(
            f"{directory_cycle_count} directory-level import cycle(s) are observed separately "
            f"and are NOT part of this score, which measures file-level cycles only."
        )
    if file_level_cycles == 0:
        limitations.append(
            "No file-level cycles were found, so this score is carried by the remaining "
            "marker(s) alone."
        )
    never_computed = [m["key"] for m in inactive if m["state"] == MARKER_NO_INPUT]
    found_nothing = [m["key"] for m in inactive if m["state"] == MARKER_ZERO_SEVERITY]
    if never_computed:
        limitations.append(
            f"Marker(s) whose input was never computed, so nothing is known either way: "
            f"{', '.join(never_computed)}."
        )
    if found_nothing:
        limitations.append(
            f"Marker(s) measured that found nothing: {', '.join(found_nothing)}. "
            f"This is evidence of absence, not absence of evidence."
        )

    return {
        "inputs_complete": all(r.inputs_complete for r in results if r.available),
        "file_level_cycle_count": file_level_cycles,
        "directory_cycle_count": directory_cycle_count,
        "active_markers": active,
        "inactive_markers": inactive,
        "limitations": limitations,
    }


def _axis_markers(results: list) -> list:
    """Every marker the axis CONSIDERED, with its threshold, weight and what
    it actually contributed across the repo.

    Stored with the snapshot rather than re-derived on read, for the same
    reason the per-file explanations are: thresholds are versioned, so a
    historical score explained with today's numbers would be explained
    wrongly. Percentile-derived markers report the repo-relative warn/saturate
    that were actually used, not the absolute pair they do not have.

    Reports mean deduction alongside fire rate deliberately -- fire rate alone
    cannot distinguish a marker that fires often and contributes nothing from
    one that dominates its category, which is the exact confusion the §10.2
    deduction report existed to resolve.
    """
    per_key: dict = {}
    order: list = []
    for r in results:
        if not r.available:
            continue
        for m in r.markers:
            if m.key not in per_key:
                per_key[m.key] = {
                    "key": m.key, "label": m.label, "category": m.category,
                    "weight": m.weight, "warn": None, "saturate": None,
                    "evaluated": 0, "fired": 0, "deductions": [],
                    "states": set(),
                }
                order.append(m.key)
            entry = per_key[m.key]
            entry["states"].add(m.state)
            if not m.available:
                continue
            entry["evaluated"] += 1
            entry["deductions"].append(m.deduction)
            if m.deduction > 0:
                entry["fired"] += 1
            if entry["warn"] is None:
                entry["warn"] = m.effective_warn
                entry["saturate"] = m.effective_saturate

    out = []
    for key in order:
        e = per_key[key]
        deductions = e["deductions"]
        states = e["states"]
        # Precedence mirrors the coverage disclosure: fired anywhere wins,
        # otherwise the strongest reason it did not.
        if "fired" in states:
            state = "fired"
        elif MARKER_ZERO_SEVERITY in states:
            state = MARKER_ZERO_SEVERITY
        elif MARKER_NOT_APPLICABLE in states:
            state = MARKER_NOT_APPLICABLE
        else:
            state = MARKER_NO_INPUT
        out.append({
            "key": e["key"], "label": e["label"], "category": e["category"],
            "weight": e["weight"], "warn": e["warn"], "saturate": e["saturate"],
            "evaluated": e["evaluated"], "fired": e["fired"],
            "fire_rate": round(e["fired"] / e["evaluated"], 4) if e["evaluated"] else None,
            "mean_deduction": round(sum(deductions) / len(deductions), 4) if deductions else None,
            "max_deduction": round(max(deductions), 4) if deductions else None,
            "state": state,
        })
    return out


def _axis_summary(results: list, axis_name: str) -> dict:
    """Repo aggregate for one axis. Reports the distribution, not just a mean:
    a lone average cannot distinguish five catastrophic files from uniform
    mediocrity (contract §12)."""
    presentable = [r for r in results if r.available and r.inputs_complete]
    values = [r.score if r.score is not None else r.points for r in presentable]
    values = [v for v in values if v is not None]

    na_reasons = {}
    for r in results:
        if not r.available:
            na_reasons[r.na_reason] = na_reasons.get(r.na_reason, 0) + 1

    summary = {
        "axis": axis_name,
        "scored": len(values),
        "na": len(results) - len(presentable),
        "na_reasons": na_reasons,
        # False when ANY file lacked a required marker input -- e.g. before
        # file-level SCCs existed. Means "complete coverage of the current
        # file-level checks", never "complete evidence".
        "inputs_complete": all(r.inputs_complete for r in results if r.available),
        "resolution_limited": any(r.resolution_limited for r in results if r.available),
        # What the axis actually considered: every marker, its threshold and
        # weight, and how much it contributed. Without this an axis panel can
        # show a score but not what produced it.
        "markers": _axis_markers(results),
        # Caps are part of the calculation too -- a category cap that binds
        # means the score understates what was measured.
        "category_caps": CATEGORY_CAPS.get(axis_name, {}),
    }
    if values:
        s = sorted(values)
        summary.update({
            "mean": round(sum(s) / len(s), 3),
            "median": round(percentile(s, 50), 3),
            "p10": round(percentile(s, 10), 3),
            "p90": round(percentile(s, 90), 3),
        })
    return summary


def create_snapshot(db: Session, repo: Repo, on_progress=None) -> CodeHealthSnapshot:
    """Score everything in memory, then write the snapshot and all per-file
    rows in a single transaction. Raises without writing anything if scoring
    fails -- there is no partial snapshot state."""
    # Computed BEFORE scoring so the snapshot records the fingerprint of the
    # content it actually measured, not of whatever the tree looks like by the
    # time the write happens.
    fingerprint = source_fingerprint(db, repo)
    inputs = collect_inputs(db, repo, on_progress=on_progress)
    ctx = build_repo_context(inputs)

    # --- everything below this line is pure computation; no DB writes yet ---
    scored = [(f, score_file(f, ctx)) for f in inputs]

    axis_summary = {}
    for axis_name in AXES:
        results = [getattr(s, axis_name) for _, s in scored]
        axis_summary[axis_name] = _axis_summary(results, axis_name)
    # Computed at snapshot time and stored, so the disclosure is immutable
    # with the result it describes rather than re-derived later against a
    # repo whose cycles may since have changed.
    axis_summary[ARCHITECTURE]["coverage"] = architecture_coverage(
        inputs, [getattr(s, ARCHITECTURE) for _, s in scored], repo)

    files_scored = sum(
        1 for _, s in scored
        if any(getattr(s, a).available and getattr(s, a).inputs_complete for a in AXES))
    files_na = len(scored) - files_scored
    # Scored on some axes but not all -- see the column comment on
    # CodeHealthSnapshot.files_partially_na for why this is stored rather than
    # left to be inferred from files_na.
    files_partially_na = sum(
        1 for _, s in scored
        if any(getattr(s, a).available for a in AXES)
        and not all(getattr(s, a).available for a in AXES))
    inputs_complete = all(axis_summary[a]["inputs_complete"] for a in AXES)

    rows = []
    for f, s in scored:
        hotspot = s.change_hotspot
        rows.append(dict(
            file_id=f.file_id, path=f.path, nloc=f.nloc,
            maintainability=s.maintainability.score,
            architecture_health=s.architecture_health.score,
            change_hotspot_points=hotspot.points,
            adjusted_exposure=(adjusted_exposure(hotspot.points, f.nloc)
                               if hotspot.points is not None else None),
            explanation={a: _explain_axis(getattr(s, a)) for a in AXES},
        ))

    # --- single transaction from here ---
    try:
        snapshot = CodeHealthSnapshot(
            repo_id=repo.id,
            branch=repo.default_branch or "",
            head_sha=repo.last_ingested_sha,
            source_fingerprint=fingerprint,
            working_tree_dirty=working_tree_dirty(repo.local_path),
            analyzer_version=ANALYZER_VERSION,
            thresholds_version=THRESHOLDS_VERSION,
            weights_version=WEIGHTS_VERSION,
            axis_summary=axis_summary,
            files_scored=files_scored,
            files_na=files_na,
            files_partially_na=files_partially_na,
            inputs_complete=inputs_complete,
        )
        db.add(snapshot)
        db.flush()  # need the id, still inside the transaction

        for row in rows:
            db.add(CodeFileHealth(snapshot_id=snapshot.id, **row))
        db.commit()
    except Exception:
        # A half-written snapshot is worse than none: a trend line cannot
        # distinguish an incomplete run from a real improvement.
        db.rollback()
        raise
    return snapshot


def previous_comparable_snapshot(
    db: Session, snapshot: CodeHealthSnapshot) -> Optional[CodeHealthSnapshot]:
    """The most recent EARLIER snapshot on the same branch whose scoring
    definition matches.

    Version equality is required, not preferred: comparing across a threshold
    change measures the change in the measuring stick, not in the code. A
    caller with no match must say "not comparable", never fall back to the
    nearest snapshot.
    """
    return (
        db.query(CodeHealthSnapshot)
        .filter(
            CodeHealthSnapshot.repo_id == snapshot.repo_id,
            CodeHealthSnapshot.branch == snapshot.branch,
            CodeHealthSnapshot.id != snapshot.id,
            CodeHealthSnapshot.computed_at <= snapshot.computed_at,
            CodeHealthSnapshot.analyzer_version == snapshot.analyzer_version,
            CodeHealthSnapshot.thresholds_version == snapshot.thresholds_version,
            CodeHealthSnapshot.weights_version == snapshot.weights_version,
        )
        .order_by(CodeHealthSnapshot.computed_at.desc(), CodeHealthSnapshot.id.desc())
        .first()
    )


def trend_delta(db: Session, snapshot: CodeHealthSnapshot) -> dict:
    """Per-axis change since the previous comparable snapshot, or an explicit
    reason why no comparison is available. Never returns 0.0 to mean
    "unknown"."""
    previous = previous_comparable_snapshot(db, snapshot)
    if previous is None:
        any_earlier = (
            db.query(CodeHealthSnapshot)
            .filter(
                CodeHealthSnapshot.repo_id == snapshot.repo_id,
                CodeHealthSnapshot.branch == snapshot.branch,
                CodeHealthSnapshot.id != snapshot.id,
                CodeHealthSnapshot.computed_at <= snapshot.computed_at,
            )
            .count()
        )
        return {
            "comparable": False,
            "reason": ("Not comparable — scoring changed since the previous snapshot."
                       if any_earlier else
                       "No previous snapshot on this branch."),
            "deltas": {},
        }

    deltas = {}
    for axis_name in AXES:
        now = (snapshot.axis_summary or {}).get(axis_name, {})
        before = (previous.axis_summary or {}).get(axis_name, {})
        if "mean" in now and "mean" in before:
            deltas[axis_name] = round(now["mean"] - before["mean"], 3)
    return {
        "comparable": True,
        "reason": None,
        "previous_snapshot_id": previous.id,
        "previous_head_sha": previous.head_sha,
        "deltas": deltas,
    }
