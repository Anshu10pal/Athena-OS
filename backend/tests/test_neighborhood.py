"""Phase 6 checkpoint 2: the file-neighbourhood query.

Four of these are canaries, and they exist because the failure this checkpoint
has to avoid is not "the answer is expensive" but "the answer is incomplete and
does not say so". A neighbourhood that quietly omits an importer sends an agent
off to change a file while hiding one of the things that will break.

  * COMPLETENESS -- both directions are present. Observed failing by removing
    the importer half, which a one-directional test would not notice.
  * UNRESOLVED IMPORTS -- carried, because a dependency the resolver could not
    pin is exactly the one an agent cannot find by looking.
  * HUB BOUND -- a high-fan-in file bounds its ENRICHMENT, never its path set,
    and the stated total is exact.
  * BOUNDARY-ONLY READ -- stubbing `read_repo_graph` must replace everything.
"""
from datetime import datetime

import pytest

from app.db.models import CodeFile, CodeFileRank, CodeImport, CodeSubsystem, Repo
from app.services.codebase import neighborhood
from app.services.codebase.graph_read import NodeT, RankT, RepoGraphT
from app.services.codebase.neighborhood import read_neighborhood


def _repo(db, n_importers=3):
    """TARGET is imported by `n_importers` files, imports two of its own (one
    in another subsystem), and has one import that does not resolve."""
    repo = Repo(host="local", owner="acme", name="nbhd",
                local_path="/nonexistent", source_kind="local")
    db.add(repo)
    db.flush()

    home = CodeSubsystem(repo_id=repo.id, algorithm="modularity", cluster_index=0,
                         member_count=2, dominant_prefix_label="core")
    far = CodeSubsystem(repo_id=repo.id, algorithm="modularity", cluster_index=1,
                        member_count=1, dominant_prefix_label="plugins")
    db.add_all([home, far])
    db.flush()

    def mk(path, sub, rank, **kw):
        f = CodeFile(repo_id=repo.id, path=path, language="python",
                     content_sha256=path, size_bytes=1, line_count=1,
                     subsystem_modularity_id=sub.id, **kw)
        db.add(f)
        db.flush()
        db.add(CodeFileRank(repo_id=repo.id, file_id=f.id, scorer="legacy",
                            score=1.0, rank=rank))
        return f

    target = mk("core/target.py", home, 1, fan_in=n_importers, fan_out=2)
    dep_near = mk("core/dep.py", home, 2)
    dep_far = mk("plugins/dep.py", far, 3)

    importers = [mk(f"core/imp{i}.py", home, 10 + i) for i in range(n_importers)]

    for dep in (dep_near, dep_far):
        db.add(CodeImport(repo_id=repo.id, from_file_id=target.id,
                          to_file_id=dep.id, raw_specifier=dep.path,
                          resolved=True, line_number=1, kind="static"))
    db.add(CodeImport(repo_id=repo.id, from_file_id=target.id, to_file_id=None,
                      raw_specifier="thirdparty.thing", resolved=False,
                      line_number=2, kind="static"))
    for imp in importers:
        db.add(CodeImport(repo_id=repo.id, from_file_id=imp.id,
                          to_file_id=target.id, raw_specifier="core/target.py",
                          resolved=True, line_number=1, kind="static"))
    # Noise: an edge between two other files, which must NOT appear.
    db.add(CodeImport(repo_id=repo.id, from_file_id=dep_near.id,
                      to_file_id=dep_far.id, raw_specifier="plugins/dep.py",
                      resolved=True, line_number=1, kind="static"))
    db.commit()
    return repo


class TestCompletenessCanary:
    """CANARY. A test asserting only one direction would pass on a query that
    silently returned imports and no importers."""

    def test_LOADBEARING_both_directions_are_present(self, db_session):
        repo = _repo(db_session, n_importers=3)
        n = read_neighborhood(db_session, repo.id, "core/target.py")

        assert {f["p"] for f in n["imports"]["files"]} == {
            "core/dep.py", "plugins/dep.py"}, "the imports half is missing or wrong"
        assert {f["p"] for f in n["importers"]["files"]} == {
            "core/imp0.py", "core/imp1.py", "core/imp2.py"}, (
            "the importers half is missing -- an agent changing this file would "
            "not be told what breaks")
        assert n["imports"]["total"] == 2
        assert n["importers"]["total"] == 3

    def test_unrelated_edges_do_not_leak_in(self, db_session):
        repo = _repo(db_session)
        n = read_neighborhood(db_session, repo.id, "core/target.py")
        paths = {f["p"] for f in n["imports"]["files"]} | {
            f["p"] for f in n["importers"]["files"]}
        assert "core/target.py" not in paths

    def test_the_file_carries_its_own_metadata(self, db_session):
        repo = _repo(db_session)
        f = read_neighborhood(db_session, repo.id, "core/target.py")["file"]
        assert f["cluster"] == "core" and f["rank"] == 1
        assert f["fan_in"] == 3 and f["fan_out"] == 2
        assert f["in_cycle"] is False

    def test_a_missing_file_raises_rather_than_returning_an_empty_neighbourhood(
            self, db_session):
        """An empty neighbourhood is a fact about a file; a missing file is a
        caller error. They must not look alike."""
        repo = _repo(db_session)
        with pytest.raises(ValueError):
            read_neighborhood(db_session, repo.id, "core/nope.py")


class TestBoundaryCrossingSignal:
    def test_it_distinguishes_local_from_rippling_change(self, db_session):
        repo = _repo(db_session)
        n = read_neighborhood(db_session, repo.id, "core/target.py")

        near = next(f for f in n["imports"]["files"] if f["p"] == "core/dep.py")
        far = next(f for f in n["imports"]["files"] if f["p"] == "plugins/dep.py")
        assert near["crosses"] is False
        assert far["crosses"] is True
        assert n["blast_radius"]["imports"] == {
            "same_subsystem": 1, "other_subsystems": 1, "unknown": 0}
        assert n["blast_radius"]["importers"]["same_subsystem"] == 3


class TestUnresolvedImportsCanary:
    """CANARY. The dependency an agent CANNOT find by looking is the one it
    most needs told."""

    def test_LOADBEARING_an_unresolved_import_appears_with_its_specifier(self, db_session):
        repo = _repo(db_session)
        n = read_neighborhood(db_session, repo.id, "core/target.py")

        assert n["imports"]["unresolved"] == [
            {"spec": "thirdparty.thing", "line": 2}], (
            "the unresolved import was dropped -- an agent editing this file "
            "would not know the dependency exists")


class TestHubBoundCanary:
    """CANARY. The bound must engage, and it must bound ENRICHMENT rather than
    the path set -- measured on superset, listing all 515 importers of the
    worst hub costs 7,458 tok, so cutting paths would trade sufficiency for a
    saving that is not needed."""

    def test_LOADBEARING_the_bound_engages_without_hiding_a_dependency(self, db_session):
        repo = _repo(db_session, n_importers=40)
        n = read_neighborhood(db_session, repo.id, "core/target.py", max_enriched=25)
        imp = n["importers"]

        assert imp["truncated_metadata"] is True, "the bound never engaged"
        assert imp["enriched"] == 25
        assert imp["total"] == 40, "the stated total must be exact, not the cut size"
        assert imp["enriched"] + len(imp["additional_paths"]) == imp["total"], (
            "a path was dropped -- the bound is hiding a real dependency, which "
            "is the failure this whole checkpoint exists to avoid")
        every = {f["p"] for f in imp["files"]} | set(imp["additional_paths"])
        assert every == {f"core/imp{i}.py" for i in range(40)}

    def test_the_enriched_window_holds_the_best_ranked(self, db_session):
        repo = _repo(db_session, n_importers=40)
        n = read_neighborhood(db_session, repo.id, "core/target.py", max_enriched=3)
        assert [f["p"] for f in n["importers"]["files"]] == [
            "core/imp0.py", "core/imp1.py", "core/imp2.py"]

    def test_a_small_neighbourhood_carries_no_truncation_keys(self, db_session):
        repo = _repo(db_session, n_importers=3)
        imp = read_neighborhood(db_session, repo.id, "core/target.py")["importers"]
        assert "additional_paths" not in imp and "truncated_metadata" not in imp


class TestSecondHop:
    def test_it_is_off_by_default(self, db_session):
        repo = _repo(db_session)
        assert "second_hop" not in read_neighborhood(
            db_session, repo.id, "core/target.py")

    def test_when_on_it_reports_the_frontier_and_its_own_truncation(self, db_session):
        repo = _repo(db_session)
        n = read_neighborhood(db_session, repo.id, "core/target.py", second_hop=True)
        hop = n["second_hop"]["imports_of_imports"]

        # core/dep.py -> plugins/dep.py, but plugins/dep.py is already a direct
        # import, so the frontier past the first hop is empty here.
        assert hop["total"] == 0 and hop["truncated"] is False
        assert "truncated" in n["second_hop"]["importers_of_importers"]


class TestSnapshotProvenanceCanary:
    """CANARY, and the completion of this query's sufficiency bar.

    Two failures are pinned, and the SECOND is the important one. A missing
    stamp leaves the consumer with no currency signal. A stamp that does not
    track the data leaves it with a FALSE one -- it reads a sha, believes the
    answer is current, and acts on a stale blast radius with more confidence
    than if the field had been absent. So the test asserts the stamp follows
    the repo row rather than merely being present and sha-shaped.
    """

    SHA = "e2bb33b1da17c16a51e54d84bcf496516d67a713"

    def test_LOADBEARING_the_result_carries_the_snapshot_it_was_built_from(self, db_session):
        repo = _repo(db_session)
        repo.last_ingested_sha = self.SHA
        repo.last_ingested_at = datetime(2026, 8, 13, 16, 26, 7)
        db_session.commit()

        n = read_neighborhood(db_session, repo.id, "core/target.py")
        assert n["snapshot"]["last_ingested_sha"] == self.SHA
        assert n["snapshot"]["last_ingested_at"].startswith("2026-08-13T16:26:07")

    def test_LOADBEARING_the_stamp_TRACKS_the_data_rather_than_being_present(self, db_session):
        """The one a hardcoded stamp passes and must not. Two repos with
        different shas must produce different stamps; a constant satisfies
        'a sha is present' while telling the consumer something false."""
        a = _repo(db_session)
        a.last_ingested_sha = self.SHA
        db_session.commit()
        first = read_neighborhood(db_session, a.id, "core/target.py")["snapshot"]

        a.last_ingested_sha = "537f0fd2dbe19e6d0fbf136c484150e567b0961f"
        db_session.commit()
        second = read_neighborhood(db_session, a.id, "core/target.py")["snapshot"]

        assert first["last_ingested_sha"] != second["last_ingested_sha"], (
            "the stamp did not move when the repo's ingested sha moved -- it is "
            "hardcoded or cached, and a consumer would read a FALSE currency "
            "signal, which is worse than none")
        assert second["last_ingested_sha"] == "537f0fd2dbe19e6d0fbf136c484150e567b0961f"

    def test_a_never_ingested_repo_stamps_null_rather_than_inventing_one(self, db_session):
        repo = _repo(db_session)
        n = read_neighborhood(db_session, repo.id, "core/target.py")
        assert n["snapshot"]["last_ingested_sha"] is None


class TestBudgetCapCanary:
    """CANARY. The cap exists to make per-query cost flat; the query exists to
    be sufficient. When those conflict the cap must LOSE, loudly.

    Measured on superset: capping `utils/core.py` at 2,000 tok leaves it 3,116
    over, because 346 importer paths cost more than the budget. The cap sheds
    the second hop and then per-neighbour metadata, and then STOPS -- it does
    not cut paths to hit the number, it reports that it could not.
    """

    def test_LOADBEARING_the_cap_never_drops_a_path_to_hit_its_number(self, db_session):
        repo = _repo(db_session, n_importers=40)
        n = read_neighborhood(db_session, repo.id, "core/target.py",
                              budget_tokens=1, count_tokens=lambda o: 10_000)
        imp = n["importers"]

        every = {f["p"] for f in imp["files"]} | set(imp.get("additional_paths", []))
        assert every == {f"core/imp{i}.py" for i in range(40)}, (
            "the budget cap dropped a dependent to fit -- a hidden importer is "
            "exactly the failure this query's correctness bar forbids")
        assert imp["total"] == 40

    def test_LOADBEARING_an_unmeetable_budget_says_so_rather_than_pretending(self, db_session):
        repo = _repo(db_session, n_importers=40)
        n = read_neighborhood(db_session, repo.id, "core/target.py",
                              budget_tokens=1, count_tokens=lambda o: 10_000)

        assert n["budget"]["applied"] is True
        assert n["budget"]["sufficiency_sacrificed"] is True, (
            "the result silently claimed to be within budget while exceeding it")
        assert n["budget"]["shortfall_tokens"] > 0

    def test_the_cap_sheds_the_cheapest_information_first(self, db_session):
        """Second hop before metadata: it is a convenience, and metadata is
        recoverable by asking again. Paths are neither."""
        repo = _repo(db_session, n_importers=40)
        calls = iter([5000, 100])          # over, then under after second_hop goes
        n = read_neighborhood(db_session, repo.id, "core/target.py", second_hop=True,
                              budget_tokens=1000, count_tokens=lambda o: next(calls, 100))
        assert n["budget"]["dropped"] == ["second_hop"]
        assert "second_hop" not in n
        assert n["importers"]["files"], "metadata was shed before the second hop"

    def test_the_default_budget_clears_the_worst_measured_hub(self):
        """The default is a MEASUREMENT, not a preference, and this pins it to
        the measurement so a later tidy-up cannot quietly round it to a nicer
        number. At `a05a0999` the worst hub on apache/superset
        (`superset/__init__.py`, 524 importers) costs 8,452 tok; Graphify's own
        default of 2,000 cannot hold it and could only reach that number by
        dropping ~500 dependents, which checkpoint 2 forbade."""
        assert neighborhood.DEFAULT_BUDGET_TOKENS >= 8_452, (
            "the default no longer clears the worst measured hub, so the cap "
            "would engage on a real file and report an unmeetable shortfall")

    def test_a_budget_that_fits_changes_nothing(self, db_session):
        repo = _repo(db_session)
        n = read_neighborhood(db_session, repo.id, "core/target.py",
                              budget_tokens=100_000, count_tokens=lambda o: 10)
        assert n["budget"] == {"limit": 100_000, "applied": False}
        assert n["importers"]["files"]

    def test_no_budget_means_no_budget_key(self, db_session):
        repo = _repo(db_session)
        assert "budget" not in read_neighborhood(db_session, repo.id, "core/target.py")


class TestBoundaryIsTheOnlyReadPath:
    """CANARY, same rule the emitter is held to."""

    def test_LOADBEARING_stubbing_the_boundary_replaces_everything(
            self, db_session, monkeypatch):
        repo = _repo(db_session)
        fake = RepoGraphT(
            repo_id=repo.id, repo_label="stub/only",
            nodes=[NodeT(path="STUB.py", language="python", size_bytes=1,
                         line_count=1, prior_category=None, fan_in=0, fan_out=0,
                         is_entry_point=False, seed_eligible=False,
                         reachable_from_entry=True, clusters={},
                         ranks=[RankT("legacy", 1.0, 1, None)])],
            edges=[], cycles=[], clusters=[])
        monkeypatch.setattr(neighborhood, "read_repo_graph",
                            lambda db, rid, **kw: fake)

        n = read_neighborhood(db_session, repo.id, "STUB.py")
        assert n["repo"] == "stub/only"
        assert n["importers"]["total"] == 0 and n["imports"]["total"] == 0
        with pytest.raises(ValueError):
            # A real file must be invisible once the boundary is stubbed.
            read_neighborhood(db_session, repo.id, "core/target.py")

    def test_the_source_contains_no_database_access(self):
        import pathlib
        src = pathlib.Path(neighborhood.__file__).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith(("#", '"""', "*", "`")))
        for forbidden in ("db.execute", "text(", "SELECT ", "from app.db.models",
                          "session.query", ".query("):
            assert forbidden not in code, f"reaches the database via {forbidden!r}"

    def test_symbols_are_not_paid_for(self, db_session, monkeypatch):
        seen = {}
        real = neighborhood.read_repo_graph
        monkeypatch.setattr(neighborhood, "read_repo_graph",
                            lambda db, rid, **kw: (seen.update(kw), real(db, rid, **kw))[1])
        repo = _repo(db_session)
        read_neighborhood(db_session, repo.id, "core/target.py")
        assert seen.get("include_symbols") is False
