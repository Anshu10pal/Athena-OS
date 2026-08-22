"""Phase 6 checkpoint 1a: the stable whole-graph read boundary.

Two of these are canaries rather than ordinary assertions, and they are the
point of the file:

  * SCHEMA DRIFT -- the boundary exists so that a renamed or dropped column
    fails HERE, loudly, instead of silently producing a graph with a field
    quietly missing. That property is worth nothing unless it has been OBSERVED
    failing, so the test drifts a real table and confirms the error names the
    table and the column.
  * UNRESOLVED EDGES -- `ranking._build_graph` filters `to_file_id.isnot(None)`
    and so cannot express "this import exists but did not resolve". The boundary
    must keep those rows, and the test fails if they are filtered out.
"""
import pytest
from sqlalchemy import text

from app.db.models import CodeFile, CodeImport, CodeSubsystem, CodeSymbol, Repo
from app.services.codebase.graph_read import (
    GraphSchemaDrift, REQUIRED_COLUMNS, read_repo_graph,
)


def _repo_with_graph(db):
    """A small repo carrying every feature the boundary claims to read:
    resolved and UNRESOLVED edges, a cycle, a cluster, ranks, symbols and an
    entry point."""
    from app.db.models import CodeFileRank
    repo = Repo(host="local", owner="acme", name="graphread",
                local_path="/nonexistent", source_kind="local")
    db.add(repo)
    db.flush()

    files = {}
    for i, path in enumerate(["pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/entry.py"]):
        f = CodeFile(repo_id=repo.id, path=path, language="python",
                     content_sha256=f"sha{i}", size_bytes=100 + i, line_count=10 + i,
                     fan_in=i, fan_out=1, seed_eligible=(path == "pkg/entry.py"),
                     is_entry_point=(path == "pkg/entry.py"))
        db.add(f)
        files[path] = f
    db.flush()

    sub = CodeSubsystem(repo_id=repo.id, algorithm="modularity", cluster_index=0,
                        member_count=2, dominant_prefix_label="pkg",
                        stable_under_perturbation=True)
    db.add(sub)
    db.flush()
    files["pkg/a.py"].subsystem_modularity_id = sub.id
    files["pkg/b.py"].subsystem_modularity_id = sub.id

    # a <-> b is a real 2-member cycle; c is alone and must NOT be reported.
    files["pkg/a.py"].scc_id = 7
    files["pkg/a.py"].scc_size = 2
    files["pkg/b.py"].scc_id = 7
    files["pkg/b.py"].scc_size = 2
    files["pkg/c.py"].scc_id = 9
    files["pkg/c.py"].scc_size = 1

    db.add(CodeImport(repo_id=repo.id, from_file_id=files["pkg/a.py"].id,
                      to_file_id=files["pkg/b.py"].id, raw_specifier="./b",
                      resolved=True, line_number=3, kind="static"))
    db.add(CodeImport(repo_id=repo.id, from_file_id=files["pkg/b.py"].id,
                      to_file_id=files["pkg/a.py"].id, raw_specifier="./a",
                      resolved=True, line_number=4, kind="static"))
    # THE UNRESOLVED ONE: a real import line pointing outside the repo.
    db.add(CodeImport(repo_id=repo.id, from_file_id=files["pkg/c.py"].id,
                      to_file_id=None, raw_specifier="requests",
                      imported_names="get", resolved=False, line_number=1,
                      kind="static"))

    db.add(CodeSymbol(file_id=files["pkg/a.py"].id, name="do_thing", kind="function",
                      signature="def do_thing(x)", line_start=5, line_end=9))
    db.add(CodeFileRank(repo_id=repo.id, file_id=files["pkg/a.py"].id,
                        scorer="legacy", score=9.5, rank=1))
    db.commit()
    return repo


class TestBoundaryShape:
    def test_it_returns_the_whole_graph_typed(self, db_session):
        repo = _repo_with_graph(db_session)
        g = read_repo_graph(db_session, repo.id)

        assert g.repo_label == "local/acme/graphread"
        assert len(g.nodes) == 4
        assert len(g.edges) == 3
        assert {n.path for n in g.nodes} == {
            "pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/entry.py"}

    def test_nodes_carry_ranks_clusters_symbols_and_entry_flags(self, db_session):
        repo = _repo_with_graph(db_session)
        g = read_repo_graph(db_session, repo.id)
        a = next(n for n in g.nodes if n.path == "pkg/a.py")

        assert a.clusters["modularity"] == "pkg", "cluster must be a LABEL, not a row id"
        assert [r.scorer for r in a.ranks] == ["legacy"]
        assert [s.name for s in a.symbols] == ["do_thing"]
        assert g.entry_points == ["pkg/entry.py"]

    def test_edges_carry_provenance(self, db_session):
        """raw_specifier, line and kind are what let a consumer say WHERE an
        import is written, not merely that it exists."""
        repo = _repo_with_graph(db_session)
        g = read_repo_graph(db_session, repo.id)
        e = next(e for e in g.edges if e.from_path == "pkg/a.py")

        assert e.raw_specifier == "./b"
        assert e.line_number == 3
        assert e.kind == "static"

    def test_a_one_member_scc_is_not_reported_as_a_cycle(self, db_session):
        """Every file is trivially its own SCC. Reporting those would make the
        whole repo 'cyclic' -- true of the datatype, false of the codebase."""
        repo = _repo_with_graph(db_session)
        g = read_repo_graph(db_session, repo.id)

        assert [c.scc_id for c in g.cycles] == [7]
        assert g.cycles[0].members == ("pkg/a.py", "pkg/b.py")
        assert next(n for n in g.nodes if n.path == "pkg/c.py").scc_id is None

    def test_symbols_can_be_excluded_without_changing_the_graph(self, db_session):
        repo = _repo_with_graph(db_session)
        full = read_repo_graph(db_session, repo.id, include_symbols=True)
        lean = read_repo_graph(db_session, repo.id, include_symbols=False)

        assert len(lean.nodes) == len(full.nodes)
        assert len(lean.edges) == len(full.edges)
        assert all(n.symbols == [] for n in lean.nodes)

    def test_an_unknown_repo_raises_rather_than_returning_an_empty_graph(self, db_session):
        """An empty graph and a missing repo must not look alike -- the first is
        a fact about a repo, the second is a caller error."""
        with pytest.raises(ValueError):
            read_repo_graph(db_session, 999_999)


class TestUnresolvedEdgesAreKept:
    """CANARY. `_build_graph` drops these; the boundary must not."""

    def test_LOADBEARING_an_unresolved_import_appears_in_the_output(self, db_session):
        repo = _repo_with_graph(db_session)
        g = read_repo_graph(db_session, repo.id)

        unresolved = [e for e in g.edges if not e.is_resolved]
        assert len(unresolved) == 1, (
            "the unresolved import was dropped -- this is exactly what "
            "ranking._build_graph does and the reason this boundary exists")
        e = unresolved[0]
        assert e.from_path == "pkg/c.py"
        assert e.to_path is None
        # The provenance is the whole value of keeping it: without the
        # specifier, "an unresolved import exists" is unactionable.
        assert e.raw_specifier == "requests"
        assert e.line_number == 1

    def test_LOADBEARING_resolved_and_unresolved_are_distinguishable(self, db_session):
        repo = _repo_with_graph(db_session)
        g = read_repo_graph(db_session, repo.id)

        assert len(g.edges) == 3
        assert g.resolved_edges == 2, (
            "a consumer must be able to count resolved edges without "
            "re-deriving what 'resolved' means")


class TestSchemaDriftFailsLoudly:
    """CANARY, and the reason the boundary exists at all.

    A boundary that returned a silently-degraded graph after a column was
    renamed would be worse than no boundary, because consumers would trust it.
    These observe the failure rather than asserting the intent.
    """

    def test_LOADBEARING_a_dropped_column_raises_a_locatable_error(self, db_session):
        repo = _repo_with_graph(db_session)
        assert read_repo_graph(db_session, repo.id).nodes, "must work before the drift"

        # Drift a real column this boundary reads. The in-memory session is
        # discarded at teardown, so this mutates nothing that outlives the test.
        db_session.execute(text("ALTER TABLE code_files DROP COLUMN scc_size"))
        db_session.commit()

        with pytest.raises(GraphSchemaDrift) as e:
            read_repo_graph(db_session, repo.id)
        msg = str(e.value)
        assert "code_files" in msg, "the error must name the TABLE"
        assert "scc_size" in msg, "the error must name the COLUMN"
        assert "graph_read.py" in msg, "and where to fix it"

    def test_LOADBEARING_a_missing_table_is_also_caught(self, db_session):
        repo = _repo_with_graph(db_session)
        db_session.execute(text("DROP TABLE code_symbols"))
        db_session.commit()

        with pytest.raises(GraphSchemaDrift) as e:
            read_repo_graph(db_session, repo.id)
        assert "code_symbols" in str(e.value)

    def test_the_drift_check_covers_every_table_the_readers_touch(self):
        """A column read by a query but absent from REQUIRED_COLUMNS would drift
        silently -- the check would pass and the query would fail deep inside
        SQLAlchemy with a driver message. Pinning the table set keeps the
        declaration and the readers honest about each other."""
        assert set(REQUIRED_COLUMNS) == {
            "repos", "code_files", "code_imports", "code_symbols",
            "code_file_ranks", "code_subsystems",
        }

    def test_LOADBEARING_the_graph_carries_the_snapshot_it_was_built_from(self, db_session):
        """A graph that cannot say which commit it reflects lets a consumer act
        on a stale blast radius without any way to notice."""
        repo = _repo_with_graph(db_session)
        repo.last_ingested_sha = "e2bb33b1da17c16a51e54d84bcf496516d67a713"
        db_session.commit()

        g = read_repo_graph(db_session, repo.id)
        assert g.last_ingested_sha == "e2bb33b1da17c16a51e54d84bcf496516d67a713"
