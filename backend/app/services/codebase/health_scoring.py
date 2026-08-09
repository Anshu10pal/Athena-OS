"""Phase 1 code health: the scoring engine.

Pure. No DB, no filesystem, no tree-sitter — it consumes already-measured
inputs (`FileInputs`) and returns scored axes with a full per-marker
explanation. That split is deliberate: `ast_metrics.py` measures,
this module judges, and thresholds/weights can therefore be re-versioned
without touching the analyzer, and be unit-tested without a repo on disk.

Implements docs/code-health-contract.md rev 2. The contract's rules that are
easy to erode are enforced structurally here rather than by convention:

- **Three axes, never blended.** There is no function that returns one number
  across axes, so there is nothing for a caller to accidentally average.
- **Direction is carried in the data.** Each axis states `direction`, and the
  health axes expose `score` (1-10, higher better) while the hotspot axis
  exposes `points` (0-9, higher = review sooner). A caller cannot silently
  read one as the other, because the other field is None.
- **N/A is a first-class state.** An unavailable marker has `deduction = 0.0`
  *and* `available = False`; aggregation must filter on `available`, never
  infer cleanliness from a zero.

`THRESHOLDS_VERSION` / `WEIGHTS_VERSION` are written into every snapshot so a
trend line can never silently compare two scoring regimes. A change to any
number below is a version bump plus a before/after distribution report — not
a silent edit.
"""
from dataclasses import dataclass, field
from typing import Optional

# v1 frozen 2026-08-09 after the raw threshold sanity pass (contract §10.1).
# v2 the same day after the per-marker DEDUCTION report (§10.2) exposed one
# semantic defect: `broad_error_handling` had warn=1, which made the FIRST
# bare `except:` deduct exactly 0.00 -- the marker only fired at two or more.
# Half the files with a broad handler on repo 1 got a free pass, and eslint's
# three such files scored a 0.0% fire rate. Only that threshold changed;
# nothing was retuned for distribution shape.
# "Frozen" means reproducible, not final: any change ships as a version bump
# with a written reason and a before/after report, never a silent edit.
THRESHOLDS_VERSION = 2
WEIGHTS_VERSION = 1

MAINTAINABILITY = "maintainability"
ARCHITECTURE = "architecture_health"
CHANGE_HOTSPOT = "change_hotspot"

HIGHER_IS_BETTER = "higher_is_better"
HIGHER_NEEDS_ATTENTION = "higher_needs_attention"

AXIS_CAP = 9.0
SUBSTANCE_FLOOR_NLOC = 10
REVIEW_COST_FLOOR_NLOC = 30


@dataclass(frozen=True)
class MarkerSpec:
    key: str
    label: str
    category: str
    weight: float
    #

    # Absolute thresholds for markers whose meaning does not depend on the
    # repo (CC 25 is extreme anywhere). None for percentile-derived markers,
    # whose warn/saturate come from RepoContext instead.
    warn: Optional[float] = None
    saturate: Optional[float] = None
    percentile_derived: bool = False


CATEGORY_CAPS = {
    MAINTAINABILITY: {"complexity": 4.0, "size": 3.0, "error": 2.0},
    ARCHITECTURE: {"cycles": 4.0, "coupling": 3.0},
    CHANGE_HOTSPOT: {"hotspot": 5.0},
}

MAINTAINABILITY_MARKERS = (
    MarkerSpec("complex_method", "Complex functions", "complexity", 2.5, warn=10, saturate=25),
    MarkerSpec("deep_nesting", "Deep nesting", "complexity", 1.5, warn=4, saturate=8),
    MarkerSpec("complex_conditional", "Complex conditionals", "complexity", 1.0, warn=4, saturate=10),
    MarkerSpec("large_method", "Large functions", "size", 2.0, warn=60, saturate=200),
    MarkerSpec("large_file", "Large file", "size", 1.5, warn=400, saturate=1500),
    # warn=0, not 1: at warn=1 the first bare `except:` deducted exactly 0.00,
    # so the marker silently required two before it said anything (§10.2).
    MarkerSpec("broad_error_handling", "Broad error handling", "error", 2.0, warn=0, saturate=5),
)

ARCHITECTURE_MARKERS = (
    MarkerSpec("cycle_participation", "Import cycle", "cycles", 4.0, warn=2, saturate=12),
    MarkerSpec("bidirectional_coupling_hub", "Bidirectional coupling hub", "coupling", 3.0,
               percentile_derived=True),
)

CHANGE_HOTSPOT_MARKERS = (
    MarkerSpec("churn_volume", "Change frequency", "hotspot", 2.5, percentile_derived=True),
    MarkerSpec("complexity_under_churn", "Complex and frequently changed", "hotspot", 2.5,
               warn=0.2, saturate=0.8),
)

ALL_MARKERS = {m.key: m for m in MAINTAINABILITY_MARKERS + ARCHITECTURE_MARKERS + CHANGE_HOTSPOT_MARKERS}


@dataclass
class FileInputs:
    """Everything the engine needs about one file. Optional fields are
    genuinely optional -- None means "not measured", which becomes N/A, and is
    never coerced to 0."""
    file_id: int
    path: str
    language: str
    nloc: int

    # AST. ast_available=False when the language has no rule set or the parse
    # failed -- see ast_metrics.metrics_for returning None.
    ast_available: bool = False
    function_count: int = 0
    max_cyclomatic: Optional[int] = None
    max_nesting: Optional[int] = None
    max_conditional_operands: Optional[int] = None
    max_function_nloc: Optional[int] = None
    broad_handler_count: Optional[int] = None

    # Import graph
    graph_available: bool = False
    fan_in: Optional[int] = None
    fan_out: Optional[int] = None
    cycle_size: Optional[int] = None  # size of the file-level SCC, None if not in one

    # Git history
    commit_count: Optional[int] = None


@dataclass
class RepoContext:
    """Repo-relative thresholds, computed once per repo. Percentile markers
    read from here so that "a lot of commits" means something against this
    codebase's own distribution rather than an imported constant."""
    churn_usable: bool = False
    churn_p50: float = 0.0
    churn_p95: float = 0.0
    fan_in_p90: float = 0.0
    fan_in_p99: float = 0.0
    fan_out_p90: float = 0.0
    fan_out_p99: float = 0.0
    churn_na_reason: Optional[str] = None


@dataclass
class MarkerResult:
    key: str
    label: str
    category: str
    weight: float
    available: bool
    deduction: float = 0.0
    severity: Optional[float] = None
    raw_value: Optional[float] = None
    # For percentile-derived markers: the repo-relative warn/saturate actually
    # used. Reported alongside the raw value so a reader can see both "12
    # commits" and "P50=1, P95=4 in this repo".
    effective_warn: Optional[float] = None
    effective_saturate: Optional[float] = None
    na_reason: Optional[str] = None

    @property
    def fired(self) -> bool:
        return self.available and self.deduction > 0


@dataclass
class AxisResult:
    axis: str
    direction: str
    available: bool
    na_reason: Optional[str] = None
    # Exactly one of these is non-None, by direction. A health axis has no
    # `points`; the hotspot axis has no `score`.
    score: Optional[float] = None
    points: Optional[float] = None
    total_deduction: float = 0.0
    markers: list = field(default_factory=list)
    category_deductions: dict = field(default_factory=dict)
    categories_capped: list = field(default_factory=list)
    axis_capped: bool = False


@dataclass
class FileScores:
    file_id: int
    path: str
    maintainability: AxisResult
    architecture_health: AxisResult
    change_hotspot: AxisResult

    def axes(self):
        return (self.maintainability, self.architecture_health, self.change_hotspot)


def percentile(sorted_values: list, p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(int(round((p / 100.0) * (len(sorted_values) - 1))), len(sorted_values) - 1)
    return float(sorted_values[idx])


def severity_for(value: float, warn: float, saturate: float) -> float:
    """Linear ramp, clamped. A degenerate range (saturate <= warn) collapses to
    a step at `warn` rather than dividing by zero -- this happens for real when
    a repo's P50 and P95 churn coincide."""
    if value <= warn:
        return 0.0
    if saturate <= warn:
        return 1.0
    if value >= saturate:
        return 1.0
    return (value - warn) / (saturate - warn)


def build_repo_context(files: list) -> RepoContext:
    """Repo-relative thresholds. `churn_usable` implements contract §5.2: fewer
    than 3 distinct commit counts means change frequency carries no
    information, and the whole Change Hotspot axis is N/A rather than ranking
    files against a constant."""
    ctx = RepoContext()

    churn = [f.commit_count for f in files if f.commit_count is not None]
    distinct = len(set(churn))
    if distinct >= 3:
        ctx.churn_usable = True
        s = sorted(churn)
        ctx.churn_p50 = percentile(s, 50)
        ctx.churn_p95 = percentile(s, 95)
    else:
        ctx.churn_usable = False
        ctx.churn_na_reason = (
            "Every file reports the same commit count, so change frequency carries no "
            "information here — typical of a shallow clone (git clone --depth 1)."
            if distinct <= 1 else
            f"Only {distinct} distinct commit counts across this repo — too little variation "
            "for change frequency to rank anything."
        )

    fan_in = sorted(f.fan_in for f in files if f.fan_in is not None)
    fan_out = sorted(f.fan_out for f in files if f.fan_out is not None)
    if fan_in:
        ctx.fan_in_p90, ctx.fan_in_p99 = percentile(fan_in, 90), percentile(fan_in, 99)
    if fan_out:
        ctx.fan_out_p90, ctx.fan_out_p99 = percentile(fan_out, 90), percentile(fan_out, 99)
    return ctx


def _na(spec: MarkerSpec, reason: str) -> MarkerResult:
    return MarkerResult(
        key=spec.key, label=spec.label, category=spec.category, weight=spec.weight,
        available=False, na_reason=reason,
    )


def _scored(spec: MarkerSpec, value: float, warn: float, saturate: float,
            severity: Optional[float] = None) -> MarkerResult:
    sev = severity_for(value, warn, saturate) if severity is None else severity
    return MarkerResult(
        key=spec.key, label=spec.label, category=spec.category, weight=spec.weight,
        available=True, severity=sev, deduction=spec.weight * sev,
        raw_value=value, effective_warn=warn, effective_saturate=saturate,
    )


def _assemble(axis: str, direction: str, markers: list) -> AxisResult:
    """Applies category caps then the axis cap, recording which bound. The
    binding flags exist so a distribution report can tell "this marker
    contributes 2.4" from "this marker would contribute 2.4 but the category
    cap already absorbed it" -- which fire rate alone cannot distinguish."""
    caps = CATEGORY_CAPS[axis]
    raw_by_cat: dict = {}
    for m in markers:
        if m.available:
            raw_by_cat[m.category] = raw_by_cat.get(m.category, 0.0) + m.deduction

    capped_by_cat = {}
    categories_capped = []
    for cat, raw in raw_by_cat.items():
        cap = caps[cat]
        capped_by_cat[cat] = min(cap, raw)
        if raw > cap:
            categories_capped.append(cat)

    total = sum(capped_by_cat.values())
    axis_capped = total > AXIS_CAP
    total = min(AXIS_CAP, total)

    result = AxisResult(
        axis=axis, direction=direction, available=True,
        total_deduction=total, markers=markers,
        category_deductions=capped_by_cat,
        categories_capped=categories_capped,
        axis_capped=axis_capped,
    )
    if direction == HIGHER_IS_BETTER:
        result.score = 10.0 - total
    else:
        result.points = total
    return result


def _unavailable(axis: str, direction: str, reason: str) -> AxisResult:
    return AxisResult(axis=axis, direction=direction, available=False, na_reason=reason)


def score_maintainability(f: FileInputs) -> AxisResult:
    if f.nloc < SUBSTANCE_FLOOR_NLOC:
        return _unavailable(MAINTAINABILITY, HIGHER_IS_BETTER,
                            f"Excluded — under {SUBSTANCE_FLOOR_NLOC} lines.")
    if not f.ast_available:
        return _unavailable(MAINTAINABILITY, HIGHER_IS_BETTER,
                            f"No analyzer rules for language '{f.language}'.")

    # A file with no functions has nothing to measure complexity ON. Size and
    # error handling still apply -- a 900-line module of constants is large
    # regardless of whether it declares a function.
    no_functions = f.function_count == 0
    complexity_na = "No functions or methods in this file."

    markers = []
    for spec in MAINTAINABILITY_MARKERS:
        value = {
            "complex_method": f.max_cyclomatic,
            "deep_nesting": f.max_nesting,
            "complex_conditional": f.max_conditional_operands,
            "large_method": f.max_function_nloc,
            "large_file": f.nloc,
            "broad_error_handling": f.broad_handler_count,
        }[spec.key]

        if spec.category == "complexity" and no_functions:
            markers.append(_na(spec, complexity_na))
        elif spec.key == "large_method" and no_functions:
            markers.append(_na(spec, complexity_na))
        elif value is None:
            markers.append(_na(spec, "Not measured."))
        else:
            markers.append(_scored(spec, float(value), spec.warn, spec.saturate))
    return _assemble(MAINTAINABILITY, HIGHER_IS_BETTER, markers)


def score_architecture_health(f: FileInputs, ctx: RepoContext) -> AxisResult:
    # Deliberately NOT gated on the substance floor (contract §5.1): a 5-line
    # barrel can sit in an import cycle or act as a coupling chokepoint, and
    # excluding it would blind this axis to files that exist to be
    # structurally significant.
    if not f.graph_available:
        return _unavailable(ARCHITECTURE, HIGHER_IS_BETTER,
                            "No ranking run has produced an import graph for this repo yet.")

    markers = []

    cycle_spec = ALL_MARKERS["cycle_participation"]
    if f.cycle_size is None:
        markers.append(_scored(cycle_spec, 0.0, cycle_spec.warn, cycle_spec.saturate))
    else:
        markers.append(_scored(cycle_spec, float(f.cycle_size), cycle_spec.warn, cycle_spec.saturate))

    hub_spec = ALL_MARKERS["bidirectional_coupling_hub"]
    if f.fan_in is None or f.fan_out is None:
        markers.append(_na(hub_spec, "Fan-in/fan-out not computed."))
    else:
        # Fires only when the file is heavily depended upon AND depends
        # heavily itself. A pure high-fan-in utility is deliberately not a
        # finding, which is why this is not called a "hub" outright.
        gate = f.fan_in >= ctx.fan_in_p90 and f.fan_out >= ctx.fan_out_p90
        warn = min(ctx.fan_in_p90, ctx.fan_out_p90)
        saturate = min(ctx.fan_in_p99, ctx.fan_out_p99)
        value = float(min(f.fan_in, f.fan_out))
        if not gate:
            r = _scored(hub_spec, value, warn, saturate, severity=0.0)
        else:
            r = _scored(hub_spec, value, warn, saturate)
        markers.append(r)

    return _assemble(ARCHITECTURE, HIGHER_IS_BETTER, markers)


def score_change_hotspot(f: FileInputs, ctx: RepoContext) -> AxisResult:
    if not ctx.churn_usable:
        return _unavailable(CHANGE_HOTSPOT, HIGHER_NEEDS_ATTENTION,
                            ctx.churn_na_reason or "Change history unusable for this repo.")
    if f.nloc < SUBSTANCE_FLOOR_NLOC:
        return _unavailable(CHANGE_HOTSPOT, HIGHER_NEEDS_ATTENTION,
                            f"Excluded — under {SUBSTANCE_FLOOR_NLOC} lines.")
    if f.commit_count is None or f.commit_count == 0:
        return _unavailable(CHANGE_HOTSPOT, HIGHER_NEEDS_ATTENTION,
                            "No history available in this clone.")

    churn_spec = ALL_MARKERS["churn_volume"]
    churn = _scored(churn_spec, float(f.commit_count), ctx.churn_p50, ctx.churn_p95)

    interaction_spec = ALL_MARKERS["complexity_under_churn"]
    if not f.ast_available or f.max_cyclomatic is None or f.function_count == 0:
        interaction = _na(interaction_spec, "Complexity not measurable for this file.")
    else:
        cc_spec = ALL_MARKERS["complex_method"]
        cc_sev = severity_for(float(f.max_cyclomatic), cc_spec.warn, cc_spec.saturate)
        product = cc_sev * (churn.severity or 0.0)
        interaction = _scored(interaction_spec, product,
                              interaction_spec.warn, interaction_spec.saturate)

    return _assemble(CHANGE_HOTSPOT, HIGHER_NEEDS_ATTENTION, [churn, interaction])


def score_file(f: FileInputs, ctx: RepoContext) -> FileScores:
    return FileScores(
        file_id=f.file_id,
        path=f.path,
        maintainability=score_maintainability(f),
        architecture_health=score_architecture_health(f, ctx),
        change_hotspot=score_change_hotspot(f, ctx),
    )


def review_cost_units(nloc: int) -> float:
    """Effort denominator, floored so a 4-line file cannot dominate the
    adjusted ranking purely by being small (contract §11)."""
    return max(nloc, REVIEW_COST_FLOOR_NLOC) / 100.0


def adjusted_exposure(points: float, nloc: int) -> float:
    return points / review_cost_units(nloc)
