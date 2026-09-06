"""Phase 8 checkpoint 1b -- GET /repos/{id}/files/{file_id}/context.

These tests are the SEVEN canaries from the checkpoint brief, each of which was
observed FAILING on deliberately broken code before it was trusted green
(§15.1). Where a break could not be constructed, that is said so explicitly
rather than passed off as a canary -- see `test_C4_...` and its docstring.

The suite calls route functions DIRECTLY rather than over HTTP (the convention
in test_repos_api.py). That is also why the endpoint takes plain defaults
instead of `Query(...)`: a marker object reached `read_neighborhood` as the
budget on the first direct call and blew up in `json.dumps`.
"""
import pytest
from sqlalchemy import text

import app.api.repos as R
from app.db.database import SessionLocal
from app.services.codebase.neighborhood import MAX_ENRICHED, _estimate_tokens

RID, FID = 6, 2256           # superset/models/core.py at a05a0999
SECONDARY = 2419             # superset/utils/core.py -- non-load-bearing


def _has_fixture(db, rid, fid):
    from app.db.models import CodeFile
    f = db.get(CodeFile, fid)
    return f is not None and f.repo_id == rid


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def resp(db):
    if not _has_fixture(db, RID, FID):
        pytest.skip("superset ingest (repo 6) not present in this database")
    return R.get_file_context(RID, FID, db=db, user=None)


def _paths(block):
    return set(f["p"] for f in block.get("files", [])) | set(block.get("additional_paths", []))


def test_C1_population_agrees_across_two_independent_routes(db, resp):
    """The SQL edge query and the payload's own paths must name the SAME files.

    Two INDEPENDENT routes on purpose: a SQL-vs-SQL comparison would re-derive
    the same population twice and could not catch a wrong one. Observed failing
    by restricting the payload route to the MAX_ENRICHED subset: 42 vs 274,
    under-pricing 84.7% of the population.
    """
    nb = resp["neighborhood"]
    payload = _paths(nb["imports"]) | _paths(nb["importers"])
    rows = db.execute(text(R._CONNECTED_FILES_SQL), {"fid": FID, "rid": RID}).mappings().all()
    ids = tuple(r["file_id"] for r in rows)
    sql = {p for (p,) in db.execute(text(f"select path from code_files where id in {ids}"))}
    assert sql == payload
    # and the break really is a break
    enriched_only = {f["p"] for f in nb["imports"]["files"]} | {f["p"] for f in nb["importers"]["files"]}
    assert len(enriched_only) <= 2 * MAX_ENRICHED < len(sql)


def test_C2_denominator_is_deduped_not_summed(resp):
    """274, strictly below the 280 edge endpoints. Observed failing at 280."""
    assert resp["connected_files_distinct"] == 274
    assert resp["edge_endpoints_total"] == 280
    assert resp["connected_files_distinct"] < resp["edge_endpoints_total"]
    assert resp["overlap_count"] == 6


def test_C3_view_tokens_price_the_subobject_not_the_envelope(resp):
    """5,062 -- reproducing the checkpoint 4b figure exactly.

    Observed failing by pricing the envelope: 5,228, a +166 drift that would
    have looked entirely plausible.
    """
    assert resp["view_tokens"] == 5062
    assert resp["view_tokens"] == _estimate_tokens(resp["neighborhood"])
    assert _estimate_tokens(resp) != resp["view_tokens"]
    assert resp["view_tokens_instrument"] == "_estimate_tokens(neighborhood)"


def test_C4_unresolved_specifiers_never_enter_the_priced_population(db, resp):
    """51 unresolved, none of them priced.

    HONEST NOTE ON THE BREAK. The obvious one -- deleting
    `AND ci.to_file_id IS NOT NULL` -- changes NOTHING (274 -> 274), because the
    join is `ON nb.id = ...to_file_id` and NULL matches no row. That clause is
    redundant, the guard is structural, and a canary built on removing it could
    not fail. The break that DOES discriminate adds the unresolved rows as
    distinct zero-byte members: population 274 -> 325 while bytes stay
    6,369,507, so the count inflates and the denominator does not.
    """
    assert resp["unresolved_excluded"] == 51
    specs = {u["spec"] for u in resp["neighborhood"]["imports"]["unresolved"]}
    rows = db.execute(text(R._CONNECTED_FILES_SQL), {"fid": FID, "rid": RID}).mappings().all()
    ids = tuple(r["file_id"] for r in rows)
    paths = {p for (p,) in db.execute(text(f"select path from code_files where id in {ids}"))}
    assert not (specs & paths)
    orphans = db.execute(
        text("select count(*) from code_imports "
             "where repo_id=:r and resolved=0 and to_file_id is not null"), {"r": RID}).scalar()
    assert orphans == 0


def test_priced_files_tripwire_equals_the_population(resp):
    """Today these are equal because size_bytes is NOT NULL and never 0. Kept as
    a separate field so the first repo where it is NOT is visible in the payload
    rather than silently under-pricing the denominator."""
    assert resp["priced_files"] == resp["connected_files_distinct"]


def test_the_neighborhood_subobject_is_returned_unmodified(db, resp):
    """Option B's whole point: the endpoint does its own extra work and does not
    touch the shape the MCP tool depends on."""
    direct = R.read_neighborhood(db, RID, resp["path"], budget_tokens=R.DEFAULT_BUDGET_TOKENS)
    assert resp["neighborhood"] == direct


def test_the_two_endpoints_disagree_by_design(db, resp):
    """`/neighbors` (100-capped, one hop) and `/context` (budget-ranked) answer
    different questions. Pinned as a test so nobody later 'fixes' the gap."""
    n = R.get_file_neighbors(RID, FID, db=db, user=None)
    ctx_total = (resp["neighborhood"]["imports"]["total"]
                 + resp["neighborhood"]["importers"]["total"])
    assert len(n["importers"]) <= R.NEIGHBORS_ENDPOINT_CAP
    assert ctx_total != len(n["importers"]) + len(n["imports"])


def test_calibration_status_is_carried_in_the_payload(resp):
    """The calibration status travels IN the response, not buried in a comment.

    SUPERSEDED IN PART AT CHECKPOINT 1c (17.16): this originally asserted
    `"UNVALIDATED" in ...`, which was correct while the divisor was the
    path-calibrated 3.6 carried over by STEP 0's NO branch. The divisor is now
    4.7, derived and conservative, so the assertion is inverted rather than
    deleted -- the property under test ("the payload states its provenance") is
    unchanged; only the value it should hold moved.
    """
    assert resp["calibration_status"] == R._CALIBRATION_STATUS
    assert "UNVALIDATED" not in resp["calibration_status"]
    assert resp["calibration_status"].startswith("derived_from_phase6_4.2")
    assert resp["connected_tokens_instrument"] == "size_bytes/_CHARS_PER_TOKEN_SOURCE"


def test_404s(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        R.get_file_context(999999, FID, db=db, user=None)
    assert e.value.status_code == 404
    if _has_fixture(db, RID, FID):
        with pytest.raises(HTTPException) as e2:
            R.get_file_context(RID, 99999999, db=db, user=None)
        assert e2.value.status_code == 404


# ---------------------------------------------------------------------------
# Checkpoint 1c -- validation against measured ground truth.
# ---------------------------------------------------------------------------

BENCH_NAIVE, BENCH_GRAPH = 1_746_672, 5_954
BENCH_RATIO = BENCH_NAIVE / BENCH_GRAPH          # 293.36


@pytest.fixture(scope="module")
def resp_2419(db):
    if not _has_fixture(db, RID, SECONDARY):
        pytest.skip("superset ingest (repo 6) not present in this database")
    return R.get_file_context(RID, SECONDARY, db=db, user=None)


def test_C5_estimate_lands_below_measured_ratio_on_the_one_benchmarked_file(resp_2419):
    """superset/utils/core.py is the ONLY file with both a tiktoken benchmark
    figure and an endpoint figure, so it is the only place the estimate can be
    checked against measured ground truth instead of against itself.

    THE THREE DIRECTIONAL ASSERTIONS ARE THE POINT, not the closeness. The UI
    estimate must land BELOW the measured ratio; if it lands above, the product
    overstates its own saving against tiktoken and ck4 must not put a ratio on
    screen.

    CANARIED by reverting the divisor to the old 3.6: the denominator assertion
    goes to 1.2785x measured and the ratio assertion to 1.1931x -- both cross
    1.0 and both fail. `view_tokens` does not move under that break, which is
    correct: it is priced by `_estimate_tokens`, not by this divisor.
    """
    d = resp_2419["connected_files_tokens"]
    v = resp_2419["view_tokens"]
    r = resp_2419["saved_ratio"]

    # Under D18 the denominator INCLUDES the centre file, which is what makes
    # this like-for-like with 4.2's naive cost ("the file PLUS every file
    # directly connected to it"). The margin narrows from 2.08% to 1.15% --
    # smaller, and now measuring the same quantity.
    assert d < BENCH_NAIVE, f"denominator {d} >= measured naive {BENCH_NAIVE}"
    assert v > BENCH_GRAPH, f"view_tokens {v} <= measured graph {BENCH_GRAPH}"
    assert r < BENCH_RATIO, f"ratio {r} >= measured ratio {BENCH_RATIO}"

    assert abs(d / BENCH_NAIVE - 1) < 0.10
    assert abs(v / BENCH_GRAPH - 1) < 0.10
    assert abs(r / BENCH_RATIO - 1) < 0.10


def test_C5_break_the_old_divisor_crosses_one_point_zero():
    """The canary's own canary: prove the assertions above CAN fail, by
    recomputing them at the superseded 3.6 rather than by trusting that they
    would. A directional assertion nobody has seen fail is not a guard."""
    at_36 = int(8_039_001 / 3.6)
    assert at_36 / BENCH_NAIVE >= 1.0
    assert (at_36 / 6_380) / BENCH_RATIO >= 1.0
    at_47 = int(8_039_001 / 4.7)
    assert at_47 / BENCH_NAIVE < 1.0
    assert (at_47 / 6_380) / BENCH_RATIO < 1.0


def test_estimator_vs_measured_is_populated_only_where_a_benchmark_exists(resp, resp_2419):
    """0.9225 on the benchmarked file, null on everything else.

    Null rather than an analogy: without a tiktoken figure the number would mean
    something different per file, and a field whose meaning the consumer cannot
    assess is worse than an absent one (17.25)."""
    # SUPERSEDED AT 3a-ter (17.16): 0.914 was correct under the exclude-self
    # denominator. D18 added the centre file's bytes, so the ratio rose to
    # 270.63 and this value to 0.923. The PROPERTY under test -- populated only
    # where a benchmark exists, and below 1.0 -- is unchanged.
    assert resp_2419["estimator_vs_measured"] == 0.9225   # 4dp as of 3a-quater
    assert resp_2419["estimator_vs_measured"] < 1.0
    assert resp["estimator_vs_measured"] is None          # models/core.py: no benchmark


def test_calibration_label_states_its_provenance(resp):
    """Replaces UNVALIDATED. The label has to carry where the number came from,
    because the constant's authority is entirely in its derivation."""
    s = resp["calibration_status"]
    assert s == ("derived_from_phase6_4.2_aggregate_tiktoken_cl100k_at_a05a0999"
                 "_rounded_conservative")
    assert "UNVALIDATED" not in s
    assert R._CHARS_PER_TOKEN_SOURCE == 4.7


# ---------------------------------------------------------------------------
# Checkpoint 1d -- connected_index.
# ---------------------------------------------------------------------------

def _sql_ids(db, fid):
    rows = db.execute(text(R._CONNECTED_FILES_SQL), {"fid": fid, "rid": RID}).mappings().all()
    return {r["file_id"] for r in rows}


@pytest.mark.parametrize("fid", [FID, SECONDARY])
def test_connected_index_ids_are_exactly_the_C1_population(db, fid):
    """The id->path map must name the SAME files the denominator priced.

    If it ever does not, the panel navigates to a set that differs from the set
    the ratio was computed over -- two populations behind one number, which is
    the failure C1 exists to catch, arriving through a different door.

    Observed failing by dropping one entry: 273 vs 274.
    """
    if not _has_fixture(db, RID, fid):
        pytest.skip("superset ingest (repo 6) not present in this database")
    r = R.get_file_context(RID, fid, db=db, user=None)
    idx_ids = {e["id"] for e in r["connected_index"]}
    assert idx_ids == _sql_ids(db, fid)
    assert len(r["connected_index"]) == r["connected_files_distinct"]
    # the break really is a break
    assert {e["id"] for e in r["connected_index"][:-1]} != _sql_ids(db, fid)


@pytest.mark.parametrize("fid", [FID, SECONDARY])
def test_connected_index_entries_carry_a_real_path(db, fid):
    """Paths come from code_files, not reconstructed -- the point of the field is
    that the caller does not have to resolve anything."""
    if not _has_fixture(db, RID, fid):
        pytest.skip("superset ingest (repo 6) not present in this database")
    from app.db.models import CodeFile
    r = R.get_file_context(RID, fid, db=db, user=None)
    for e in r["connected_index"][:20]:
        assert db.get(CodeFile, e["id"]).path == e["path"]


def test_adding_an_envelope_sibling_does_NOT_move_view_tokens(resp, resp_2419):
    """C3's FIRST LIVE TEST, and the reason it was worth pinning a boundary.

    `connected_index` is a new envelope sibling -- exactly the change that would
    move `view_tokens` if it priced the envelope rather than the neighbourhood
    sub-object. 5,062 and 6,380 are the pre-`connected_index` values; if either
    moved, C3's boundary was drawn in the wrong place and the number the UI shows
    would drift every time the envelope grew.
    """
    assert resp["view_tokens"] == 5062
    assert resp_2419["view_tokens"] == 6380
    assert resp["view_tokens"] == _estimate_tokens(resp["neighborhood"])
    assert resp_2419["view_tokens"] == _estimate_tokens(resp_2419["neighborhood"])
    # and the envelope demonstrably DID grow
    assert _estimate_tokens(resp) > resp["view_tokens"]


def test_denominator_and_ratio_unchanged_by_connected_index(resp, resp_2419):
    """The addition is presentational. If it moved the priced population or the
    ratio, it would not be presentational."""
    # SUPERSEDED AT 3a-ter (17.16): these were the exclude-self figures.
    # D18 includes the centre file's own size_bytes in the denominator, so
    # 2256 moves 1,355,214 -> 1,368,803 (ratio 267.72 -> 270.41) and 2419
    # moves 1,710,425 -> 1,726,621 (268.09 -> 270.63). The property under
    # test -- that ck1d/ck3a's additions did not move these -- is unchanged.
    assert resp["connected_files_tokens"] == 1_368_803
    assert round(resp["saved_ratio"], 2) == 270.41
    assert resp_2419["connected_files_tokens"] == 1_726_621
    assert round(resp_2419["saved_ratio"], 2) == 270.63


# ---------------------------------------------------------------------------
# Checkpoint 3a -- direction, subsystem id, unresolved_edges.
# ---------------------------------------------------------------------------

DIRECTION_EXPECT = {
    #        distinct, imports-side, importers-side, both, unresolved
    FID:      (274, 22, 258, 6, 51),
    SECONDARY: (355, 11, 346, 2, 78),
}


@pytest.mark.parametrize("fid", [FID, SECONDARY])
def test_direction_counts_reconcile_exactly(db, fid):
    """imports + importers - both == distinct, per side, not just in total.

    THE PER-SIDE ASSERTION IS THE POINT. Swapping from_file_id/to_file_id in the
    CASE branch PRESERVES the total (274 stays 274) and preserves `both`, so a
    length-only or total-only assertion passes the swap clean. Observed failing
    on that swap: 2256 inverts to 258/22 and 2419 to 346/11.
    """
    if not _has_fixture(db, RID, fid):
        pytest.skip("superset ingest (repo 6) not present in this database")
    distinct, exp_imports, exp_importers, exp_both, _ = DIRECTION_EXPECT[fid]
    ci = R.get_file_context(RID, fid, db=db, user=None)["connected_index"]

    imports_side = sum(1 for e in ci if e["direction"] in ("imports", "both"))
    importers_side = sum(1 for e in ci if e["direction"] in ("importedBy", "both"))
    both = sum(1 for e in ci if e["direction"] == "both")

    assert imports_side == exp_imports
    assert importers_side == exp_importers
    assert both == exp_both
    assert exp_imports + exp_importers - exp_both == distinct == len(ci)
    assert {e["direction"] for e in ci} <= {"imports", "importedBy", "both"}


@pytest.mark.parametrize("fid", [FID, SECONDARY])
def test_direction_matches_the_neighbourhood_totals(db, fid):
    """The direction split must agree with `read_neighborhood`'s own totals --
    two independent routes to the same two numbers, as C1 does for population."""
    if not _has_fixture(db, RID, fid):
        pytest.skip("superset ingest (repo 6) not present in this database")
    d = R.get_file_context(RID, fid, db=db, user=None)
    ci, nb = d["connected_index"], d["neighborhood"]
    assert sum(1 for e in ci if e["direction"] in ("imports", "both")) == nb["imports"]["total"]
    assert sum(1 for e in ci if e["direction"] in ("importedBy", "both")) == nb["importers"]["total"]


@pytest.mark.parametrize("fid", [FID, SECONDARY])
def test_connected_index_carries_subsystem_id_from_code_files(db, fid):
    """D15: this is the ONLY colour source for the Context view. Verified against
    code_files directly, not against the neighbourhood's `cluster` field -- which
    covers only the 25 enriched entries and is deliberately not consulted."""
    if not _has_fixture(db, RID, fid):
        pytest.skip("superset ingest (repo 6) not present in this database")
    from app.db.models import CodeFile
    ci = R.get_file_context(RID, fid, db=db, user=None)["connected_index"]
    assert all("subsystem_modularity_id" in e for e in ci)
    for e in ci[:25]:
        assert db.get(CodeFile, e["id"]).subsystem_modularity_id == e["subsystem_modularity_id"]


@pytest.mark.parametrize("fid", [FID, SECONDARY])
def test_unresolved_edges_are_display_only_and_never_priced(db, fid):
    """Length equals `unresolved_excluded`, and no specifier reaches the priced
    population. Folding these in would inflate the count while
    `connected_bytes` stayed put -- the C4 failure, arriving via a new field."""
    if not _has_fixture(db, RID, fid):
        pytest.skip("superset ingest (repo 6) not present in this database")
    _, _, _, _, exp_unres = DIRECTION_EXPECT[fid]
    d = R.get_file_context(RID, fid, db=db, user=None)
    ue = d["unresolved_edges"]
    assert len(ue) == d["unresolved_excluded"] == exp_unres
    assert all(set(u) == {"raw_specifier", "line_number", "kind"} for u in ue)
    specs = {u["raw_specifier"] for u in ue}
    assert not (specs & {e["path"] for e in d["connected_index"]})
    # the priced population is untouched by their presence
    assert d["priced_files"] == d["connected_files_distinct"] == len(d["connected_index"])


def test_ck3a_additions_did_NOT_move_view_tokens(resp, resp_2419):
    """C3's SECOND live test, and the additions are much larger this time --
    direction and subsystem id on every entry, plus a whole new
    `unresolved_edges` array. Still 5,062 and 6,380."""
    assert resp["view_tokens"] == 5062
    assert resp_2419["view_tokens"] == 6380
    # SUPERSEDED AT 3a-ter (17.16): the denominator figures below were the
    # exclude-self ones. D18 moved them to 1,368,803 / 270.41 and
    # 1,726,621 / 270.63. What this test is FOR -- that ck3a's additions did
    # not move them -- is unaffected by which denominator is correct.
    assert resp["connected_files_tokens"] == 1_368_803
    assert resp_2419["connected_files_tokens"] == 1_726_621
    assert round(resp["saved_ratio"], 2) == 270.41
    assert round(resp_2419["saved_ratio"], 2) == 270.63


# ---------------------------------------------------------------------------
# Checkpoint 3a-ter -- D18 denominator scope, and the honest floor.
# ---------------------------------------------------------------------------

FLOOR = 1107          # scripts/__init__.py -- 785 bytes, ZERO connections


@pytest.fixture(scope="module")
def resp_floor(db):
    if not _has_fixture(db, RID, FLOOR):
        pytest.skip("superset ingest (repo 6) not present in this database")
    return R.get_file_context(RID, FLOOR, db=db, user=None)


@pytest.mark.parametrize("fid,own,expect_bytes,expect_tokens", [
    (FID, 63_868, 6_433_375, 1_368_803),
    (SECONDARY, 76_119, 8_115_120, 1_726_621),
])
def test_D18_denominator_includes_the_centre_file(db, fid, own, expect_bytes, expect_tokens):
    """The bytes include self; the COUNT does not. That asymmetry is deliberate.

    Corrected at 3a-ter because the exclude-self version was accepted on a 1.1%
    margin measured on a 355-connection hub -- a scale-dependent figure quoted
    as a property of the method. At the floor the same divergence is TOTAL.
    """
    from app.db.models import CodeFile
    d = R.get_file_context(RID, fid, db=db, user=None)
    assert db.get(CodeFile, fid).size_bytes == own
    assert d["connected_bytes"] == expect_bytes
    assert d["connected_files_tokens"] == expect_tokens
    # the count is untouched -- 3b-1's three identities are pinned to it
    distinct, exp_imports, exp_importers, exp_both, _ = DIRECTION_EXPECT[fid]
    assert d["connected_files_distinct"] == distinct
    # edge_endpoints_total is imports + importers, NOT DIRECTION_EXPECT[fid][1]
    # (which is the imports side alone -- my first version asserted 280 == 22).
    assert d["edge_endpoints_total"] == exp_imports + exp_importers
    assert len(d["connected_index"]) == d["connected_files_distinct"]
    # and the bytes really do differ from the exclude-self sum
    assert d["connected_bytes"] == own + sum(
        r["size_bytes"] for r in db.execute(
            text(R._CONNECTED_FILES_SQL), {"fid": fid, "rid": RID}).mappings())


def test_D18_did_not_move_view_tokens(resp, resp_2419):
    """C3's FOURTH live test. The denominator changed; the priced payload did
    not, and `view_tokens` prices only the neighbourhood sub-object."""
    assert resp["view_tokens"] == 5062
    assert resp_2419["view_tokens"] == 6380


def test_estimator_vs_measured_stays_below_one_after_D18(resp_2419):
    """0.923 (raw 0.92253). Still under 1.0, so the estimate lands below the
    tiktoken-measured ratio and ck4 may show a number.

    Canaried against the reverted exclude-self denominator: 0.9139, also under
    1.0. The direction holds either way -- this is a coherence check, not the
    guard, and it is recorded as such so nobody reads it as proof that D18 was
    what kept the estimate honest.
    """
    assert resp_2419["estimator_vs_measured"] == 0.9225   # 4dp as of 3a-quater
    assert resp_2419["estimator_vs_measured"] < 1.0


class TestTheHonestFloor:
    """scripts/__init__.py: 785 bytes, zero connections.

    THE MOST ATTACKABLE NUMBER IN THE FEATURE, and the endpoint had never been
    called on it before 3a-ter. A sub-1x ratio is a REAL RESULT -- the graph
    costs more than reading the file -- and Phase 6 reports it deliberately as
    the floor of a 0.93x-293x spread. It must reach the payload intact.
    """

    def test_zero_connection_shape(self, resp_floor):
        assert resp_floor["path"] == "scripts/__init__.py"
        assert resp_floor["connected_files_distinct"] == 0
        assert resp_floor["edge_endpoints_total"] == 0
        assert resp_floor["overlap_count"] == 0
        assert resp_floor["connected_index"] == []
        assert resp_floor["unresolved_edges"] == []
        assert resp_floor["priced_files"] == 0

    def test_the_denominator_is_the_file_itself_not_zero(self, resp_floor):
        """Before D18 this was 0 -- a 100% divergence from the benchmark at
        exactly the point the spread bottoms out."""
        assert resp_floor["connected_bytes"] == 785
        assert resp_floor["connected_files_tokens"] == 167

    def test_LOADBEARING_saved_tokens_is_NEGATIVE_and_unclamped(self, resp_floor):
        """Observed failing with `max(0, ...)` in the path: saved_tokens becomes
        0 and saved_ratio 0.994 survives, so the clamp hides the sign while
        leaving the ratio looking plausible -- the §17.25 shape exactly."""
        assert resp_floor["saved_tokens"] == -1
        assert resp_floor["saved_tokens"] < 0
        # not clamped, not absolute-valued, not floored
        assert resp_floor["saved_tokens"] != 0
        assert resp_floor["saved_tokens"] != 1

    def test_LOADBEARING_saved_ratio_is_below_one_and_unclamped(self, resp_floor):
        assert resp_floor["saved_ratio"] < 1.0
        assert round(resp_floor["saved_ratio"], 4) == 0.994
        assert resp_floor["saved_ratio"] > 0        # not floored to zero either

    def test_the_ratio_is_internally_consistent(self, resp_floor):
        d = resp_floor
        assert d["saved_tokens"] == d["connected_files_tokens"] - d["view_tokens"]
        assert d["saved_ratio"] == d["connected_files_tokens"] / d["view_tokens"]

    def test_no_clamping_expression_exists_anywhere_in_the_path(self):
        """A source-level tripwire, limits stated: it reads text, covers the one
        function, and proves no clamp is WRITTEN rather than that none can
        occur. Cheap insurance against someone 'fixing' a negative saving."""
        import inspect
        src = inspect.getsource(R.get_file_context)
        # `or 0` is deliberately NOT in this list: `(file.size_bytes or 0)` is a
        # null-coalesce on a nullable column, not a clamp on the saving. Banning
        # it flagged correct code -- a tripwire whose first catch is a false
        # positive teaches people to delete tripwires.
        for banned in ("max(0", "abs(", "if saved_tokens < 0", "max(saved"):
            assert banned not in src, f"clamping expression {banned!r} in the path"


# ---------------------------------------------------------------------------
# Checkpoint 3a-quater -- the estimator's MEASURED error envelope.
# ---------------------------------------------------------------------------

# our/measured RATIO for each §4.2 file, measured 2026-09-04 at 4.7. These are
# OBSERVATIONS, not targets: they pin the envelope so a future change to the
# estimator, the divisor or the payload shape has to acknowledge moving it.
MEASURED_ENVELOPE = {
    "scripts/__init__.py":                                     (0,   1.0740),
    "superset/commands/annotation_layer/annotation/create.py":  (6,   1.0613),
    "superset/commands/chart/delete.py":                        (10,  1.0910),
    "superset/utils/core.py":                                   (355, 0.9225),
    "superset/__init__.py":                                     (524, 0.9721),
}
ENVELOPE_LO, ENVELOPE_HI = 0.9225, 1.0910


@pytest.mark.parametrize("path,conn,expected", [
    (p, c, r) for p, (c, r) in MEASURED_ENVELOPE.items()])
def test_estimator_error_envelope_per_benchmark_file(db, path, conn, expected):
    """Every §4.2 file, both instruments, pinned to 4dp.

    THE POINT IS THE ENVELOPE, NOT ANY ONE FILE. The pre-registered invariant
    "estimator_vs_measured < 1.0" was FALSE and survived four checkpoints
    because every file checked was a hub. This parametrisation spans 0 to 524
    connections precisely so a one-sided claim cannot pass again.
    """
    from app.db.models import CodeFile
    row = db.query(CodeFile).filter(CodeFile.repo_id == RID, CodeFile.path == path).first()
    if row is None:
        pytest.skip("superset ingest (repo 6) not present in this database")
    d = R.get_file_context(RID, row.id, db=db, user=None)
    assert d["connected_files_distinct"] == conn
    assert d["estimator_vs_measured"] == expected
    assert ENVELOPE_LO <= d["estimator_vs_measured"] <= ENVELOPE_HI


def test_the_envelope_is_TWO_SIDED_and_straddles_one(db):
    """The retired invariant, stated as what it actually is.

    Below ~1.0 we UNDERSTATE the saving; above it we OVERSTATE it. Both occur in
    real data, so ck4's label must be true about both directions -- an
    'at least Nx' framing is false at the floor and a 'exactly Nx' framing is
    false everywhere.
    """
    vals = [r for _, r in MEASURED_ENVELOPE.values()]
    assert min(vals) < 1.0 < max(vals), "the envelope must straddle 1.0"
    assert min(vals) == ENVELOPE_LO
    assert max(vals) == ENVELOPE_HI
    # and it sits inside the 0.90-1.10 window ck4 can honestly label,
    # with only 0.009 of headroom at the top -- recorded so a future widening
    # is noticed rather than absorbed.
    assert 0.90 <= ENVELOPE_LO and ENVELOPE_HI <= 1.10


def test_the_crossover_is_a_BRACKET_not_a_point():
    """Where our/measured crosses 1.0: between 10 and 355 connected files.

    A 345-wide bracket with NO measurement inside it. Asserted as a bracket
    because interpolating a crossover from five non-monotonic points would be
    inventing a number -- and the non-monotonicity is real: R runs
    1.0740 -> 1.0613 -> 1.0910 -> 0.9225 -> 0.9721. That is also the empirical
    case against a size-dependent divisor (D19).
    """
    above = {c for c, r in MEASURED_ENVELOPE.values() if r > 1.0}
    below = {c for c, r in MEASURED_ENVELOPE.values() if r < 1.0}
    assert max(above) == 10
    assert min(below) == 355
    assert not any(10 < c < 355 for c in above | below)
    ordered = [r for _, r in sorted(MEASURED_ENVELOPE.values())]
    assert ordered != sorted(ordered) and ordered != sorted(ordered, reverse=True)


def test_D19_the_divisor_is_a_single_fixed_constant(db):
    """Not size-dependent, not interpolated. One constant, one label, an error
    envelope measured rather than tuned away."""
    assert R._CHARS_PER_TOKEN_SOURCE == 4.7
    assert isinstance(R._CHARS_PER_TOKEN_SOURCE, float)
    # the same divisor priced the floor and the biggest hub
    from app.db.models import CodeFile
    ids = [db.query(CodeFile).filter(CodeFile.repo_id == RID, CodeFile.path == p).first()
           for p in ("scripts/__init__.py", "superset/__init__.py")]
    if any(x is None for x in ids):
        pytest.skip("superset ingest (repo 6) not present in this database")
    for row in ids:
        d = R.get_file_context(RID, row.id, db=db, user=None)
        assert d["connected_files_tokens"] == int(d["connected_bytes"] / 4.7)


# ---------------------------------------------------------------------------
# Checkpoint 4 -- D25/D26 display strings.
# ---------------------------------------------------------------------------

class TestConservativeRounding:
    """D25: rounding NEVER favours us.

    Canaried against `round()` rather than `math.floor`: Python's round is
    half-to-even, so `round(0.9940, 1)` is 1.0 -- which turns "the graph costs
    MORE on this file" into "break-even", erasing the one result Phase 6 reports
    specifically in order to be honest. Both directions are asserted below.
    """

    def test_the_floor_file_shows_NO_ratio(self, resp_floor):
        """SUPERSEDED AT ck5 (17.16). This asserted `~0.99x` on the floor file
        and that it never rounds to 1 -- correct while zero-connection files
        still displayed a ratio at all. D29 retired that display: the ratio is
        arithmetically fine and semantically void with nothing to substitute
        for, and it INVERTED on large unconnected files (~10.9x on an 18KB one).

        The property under test -- "this file never claims a saving it does not
        have" -- is unchanged and now holds more strongly: there is no number.
        The conservative-rounding behaviour itself is still covered by
        `test_every_band_cuts_downward`, which exercises the formatter directly.
        """
        assert resp_floor["ratio_display"] is None
        assert resp_floor["ratio_absent_reason"] is not None
        # the formatter is still conservative where it IS used
        assert R._format_saved_ratio(0.9940) == "~0.99x"

    def test_2256_is_270(self, resp):
        # 270.4075. My first version asserted `> 270.6` here -- that is 2419's
        # raw value, not this one, and 268.09 was 2419's PRE-D18 figure. Both
        # caught by these tests failing.
        assert resp["ratio_display"] == "~270x"
        assert 270.4 < resp["saved_ratio"] < 270.5

    def test_2419_is_270_where_rounding_UP_would_have_said_271(self, resp_2419):
        """The file where the floor-vs-round choice actually bites.

        2419's raw ratio is 270.6303, which `round()` takes to 271 -- half a
        unit of saving we did not measure. `math.floor` keeps it at 270.
        """
        assert resp_2419["ratio_display"] == "~270x"
        assert resp_2419["saved_ratio"] > 270.5          # would round UP
        assert "271" not in resp_2419["ratio_display"]

    def test_two_different_files_can_share_a_display_string(self, resp, resp_2419):
        """270.4075 and 270.6303 both print `~270x`, and that is correct rather
        than a bug: the difference between them (0.22) is far inside the
        measured -8%/+9% envelope, so displaying it would be false precision --
        exactly what D25 exists to prevent."""
        assert resp["saved_ratio"] != resp_2419["saved_ratio"]
        assert resp["ratio_display"] == resp_2419["ratio_display"] == "~270x"

    def test_LOADBEARING_round_would_produce_the_dishonest_string(self):
        """The canary's canary: prove the naive implementation fails.

        If this ever stops failing, `round` became safe and the argument in the
        code comment is stale -- which is worth knowing.
        """
        assert f"~{round(0.9940, 1)}x" == "~1.0x"          # the dishonest string
        assert R._format_saved_ratio(0.9940) == "~0.99x"   # ours
        assert f"~{round(270.6303):,.0f}x" == "~271x"      # rounds UP, favouring us
        assert R._format_saved_ratio(270.6303) == "~270x"

    def test_every_band_cuts_downward(self):
        for raw, expect in [
            (270.6303, "~270x"), (268.0917, "~268x"), (100.9, "~100x"),
            (99.99, "~99.9x"), (15.86, "~15.8x"), (9.999, "~9.99x"),
            (1.0, "~1.00x"), (0.9999, "~0.99x"), (0.9940, "~0.99x"),
        ]:
            got = R._format_saved_ratio(raw)
            assert got == expect, f"{raw} -> {got}, expected {expect}"
            # never rounds up
            assert float(got.strip("~x").replace(",", "")) <= raw

    def test_none_ratio_yields_no_string(self):
        assert R._format_saved_ratio(None) is None


def test_envelope_pct_states_the_measured_band(resp):
    """From ck3a-quater: 0.9225-1.0910 across the five benchmark files. Stated
    as an asymmetric range because it IS asymmetric -- a +/-9% would overstate
    the low side."""
    assert resp["envelope_pct"] == "-8% / +9%"
    assert resp["envelope_pct"] == R._envelope_pct()


def test_display_strings_are_present_where_a_ratio_IS_claimed(resp, resp_2419, resp_floor):
    """SUPERSEDED IN PART AT ck5 (17.16): this required a ratio string on EVERY
    file, including the floor. D29 makes it absent where there are no connected
    files, so the requirement now splits -- a string where a saving is claimed,
    null plus a reason where none is."""
    for d in (resp, resp_2419):
        assert isinstance(d["ratio_display"], str)
        assert d["ratio_display"].startswith("~")
        assert d["ratio_display"].endswith("x")
    assert resp_floor["ratio_display"] is None
    # the envelope is a property of the estimator and travels regardless
    for d in (resp, resp_2419, resp_floor):
        assert d["envelope_pct"] == "-8% / +9%"


# ---------------------------------------------------------------------------
# Checkpoint 5 -- D29: the ratio is ABSENT at zero connections.
# ---------------------------------------------------------------------------

ZERO_CONN_LARGE = 6149   # AlertReportList.test.tsx, 18KB, 0 connections


class TestD29RatioAbsentAtZeroConnections:
    """The ck4-bis defect, closed.

    An 18KB unconnected file displayed `~10.9x` under the caption "cheaper than
    reading every connected file" -- about an empty set. With zero connections
    the denominator collapses to the file's OWN bytes (D18 includes the centre),
    so the ratio stops measuring substitution and starts measuring
    file-size-over-a-constant.

    CANARIED. Restoring the unconditional call brings `~10.9x` straight back on
    this file and `~0.99x` on scripts/__init__.py; suppressing universally strips
    2256's `~270x`. Both observed before trusting green.
    """

    def test_LOADBEARING_the_large_unconnected_file_has_no_ratio(self, db):
        if not _has_fixture(db, RID, ZERO_CONN_LARGE):
            pytest.skip("superset ingest (repo 6) not present")
        d = R.get_file_context(RID, ZERO_CONN_LARGE, db=db, user=None)
        assert d["connected_files_distinct"] == 0
        assert d["ratio_display"] is None
        # the raw ratio is still computed and still large -- it is the DISPLAY
        # that is suppressed, so the underlying number stays auditable
        assert d["saved_ratio"] > 10

    def test_null_not_a_sentinel_string(self, db, resp_floor):
        if not _has_fixture(db, RID, ZERO_CONN_LARGE):
            pytest.skip("superset ingest (repo 6) not present")
        for d in (R.get_file_context(RID, ZERO_CONN_LARGE, db=db, user=None), resp_floor):
            assert d["ratio_display"] is None
            assert not isinstance(d["ratio_display"], str)

    def test_ck4s_amber_floor_display_is_retired(self, resp_floor):
        """scripts/__init__.py stops showing ~0.99x. It was right by accident
        for small unconnected files and inverted for large ones."""
        assert resp_floor["ratio_display"] is None

    def test_not_clamped_to_one(self, db, resp_floor):
        for bad in ("~1x", "~1.0x", "~1.00x"):
            assert resp_floor["ratio_display"] != bad

    def test_component_costs_survive_and_stay_real(self, db, resp_floor):
        if not _has_fixture(db, RID, ZERO_CONN_LARGE):
            pytest.skip("superset ingest (repo 6) not present")
        big = R.get_file_context(RID, ZERO_CONN_LARGE, db=db, user=None)
        assert big["graph_cost_display"] == "351 tokens"
        assert big["read_cost_display"] == "3,844 tokens"
        assert resp_floor["graph_cost_display"] == "168 tokens"
        assert resp_floor["read_cost_display"] == "167 tokens"

    def test_the_reason_is_supplied_by_the_backend(self, resp_floor):
        r = resp_floor["ratio_absent_reason"]
        assert isinstance(r, str)
        assert "nothing for the graph to substitute for" in r
        assert "two different questions" in r

    def test_REGRESSION_GUARD_suppression_is_scoped_not_universal(self, resp, resp_2419):
        """Break by returning None unconditionally and both of these fail."""
        assert resp["ratio_display"] == "~270x"
        assert resp_2419["ratio_display"] == "~270x"
        assert resp["ratio_absent_reason"] is None
        assert resp_2419["ratio_absent_reason"] is None
