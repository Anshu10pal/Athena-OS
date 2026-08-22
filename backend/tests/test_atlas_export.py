"""Phase 6 checkpoint 1b: the atlas emitter.

Three of these are canaries rather than ordinary assertions:

  * MODE SWITCH -- a test that asserts "this repo emits whole_graph mode" would
    pass whether or not a threshold existed. So the switch is observed firing
    BOTH WAYS over the same repo, by moving the threshold across it, and the
    artifact's own stated mode is checked each time. A consumer that cannot
    tell a scoped artifact from a complete one will reason over a partial graph
    believing it whole (§17.25).
  * BOUNDARY-ONLY READ -- checkpoint 1a exists to make `read_repo_graph` the
    single read path. The emitter is stubbed at that boundary and must produce
    NOTHING but the stub's content; any real data surviving the stub means it
    reached around the boundary into tables.
  * UNRESOLVED EDGES -- carried through from the boundary, including in scoped
    mode, and distinguishable from resolved ones without null-testing.
"""
import json

import pytest

from app.db.models import CodeFile, CodeFileRank, CodeImport, CodeSubsystem, Repo
from app.services.codebase import atlas_export
from app.services.codebase.atlas_export import (
    MODE_SCOPED, MODE_WHOLE, choose_mode, export_atlas, serialize,
)
from app.services.codebase.graph_read import NodeT, RankT, RepoGraphT


def _repo(db, n_files=6):
    repo = Repo(host="local", owner="acme", name="atlas",
                local_path="/nonexistent", source_kind="local")
    db.add(repo)
    db.flush()

    sub = CodeSubsystem(repo_id=repo.id, algorithm="modularity", cluster_index=0,
                        member_count=2, dominant_prefix_label="pkg")
    # A second clustering that must NOT reach the artifact -- three partitions
    # of the same files is three times the tokens for one question.
    other = CodeSubsystem(repo_id=repo.id, algorithm="louvain", cluster_index=0,
                          member_count=3, dominant_prefix_label="louvain-only")
    db.add_all([sub, other])
    db.flush()

    files = []
    for i in range(n_files):
        f = CodeFile(repo_id=repo.id, path=f"pkg/f{i}.py", language="python",
                     content_sha256=f"sha{i}", size_bytes=10, line_count=5,
                     fan_in=i, fan_out=1, seed_eligible=(i == 0),
                     is_entry_point=(i == 0),
                     subsystem_modularity_id=sub.id,
                     subsystem_louvain_id=other.id)
        db.add(f)
        files.append(f)
    db.flush()

    # rank 1 is the BEST rank, so f0 survives scoping and the last file does not.
    for i, f in enumerate(files):
        db.add(CodeFileRank(repo_id=repo.id, file_id=f.id, scorer="legacy",
                            score=1.0, rank=i + 1))
    # Resolved chain f0 -> f1 -> f2 ...
    for i in range(n_files - 1):
        db.add(CodeImport(repo_id=repo.id, from_file_id=files[i].id,
                          to_file_id=files[i + 1].id, raw_specifier=f"./f{i+1}",
                          resolved=True, line_number=1, kind="static"))
    # One import that does not resolve -- from the FIRST file, so it survives
    # scoping and the scoped case can assert on it too.
    db.add(CodeImport(repo_id=repo.id, from_file_id=files[0].id, to_file_id=None,
                      raw_specifier="requests", resolved=False, line_number=2,
                      kind="static"))
    db.commit()
    return repo


class TestArtifactShape:
    def test_it_emits_paths_not_database_ids(self, db_session):
        repo = _repo(db_session)
        art = export_atlas(db_session, repo.id)

        assert all(n["p"].startswith("pkg/") for n in art["nodes"])
        assert all(isinstance(a, str) and isinstance(b, str)
                   for a, b in art["edges"]), "edges must be paths, not ids"

    def test_nulls_are_dropped_rather_than_emitted(self, db_session):
        repo = _repo(db_session)
        art = export_atlas(db_session, repo.id)

        assert all(None not in n.values() for n in art["nodes"])
        # f0 is the only entry point, so no other node may carry the key at all.
        assert [n["p"] for n in art["nodes"] if "entry" in n] == ["pkg/f0.py"]

    def test_only_the_artifact_clustering_travels(self, db_session):
        repo = _repo(db_session)
        art = export_atlas(db_session, repo.id)

        labels = {c["label"] for c in art["clusters"]}
        assert labels == {"pkg"}, "a second clustering leaked into the artifact"
        assert all(n.get("cluster") == "pkg" for n in art["nodes"])

    def test_a_one_member_scc_never_appears_as_a_cycle(self, db_session):
        """Carried from the boundary; asserted here because the artifact is
        what a consumer actually reads."""
        repo = _repo(db_session)
        art = export_atlas(db_session, repo.id)
        assert all("scc" not in n for n in art["nodes"])

    def test_serialize_is_compact(self, db_session):
        repo = _repo(db_session)
        s = serialize(export_atlas(db_session, repo.id))
        assert ", " not in s and '": ' not in s, "default separators waste a byte per element"
        assert json.loads(s)["atlas"]["mode"] == MODE_WHOLE


class TestModeSwitchCanary:
    """CANARY. Asserting one repo's mode would pass with no threshold at all,
    so the switch is observed firing BOTH WAYS across the same repo."""

    def test_LOADBEARING_the_switch_fires_in_both_directions(self, db_session, monkeypatch):
        repo = _repo(db_session, n_files=6)

        monkeypatch.setattr(atlas_export, "WHOLE_GRAPH_MAX_FILES", 10)
        below = export_atlas(db_session, repo.id)

        monkeypatch.setattr(atlas_export, "WHOLE_GRAPH_MAX_FILES", 3)
        monkeypatch.setattr(atlas_export, "SCOPED_MAX_FILES", 3)
        above = export_atlas(db_session, repo.id)

        assert below["atlas"]["mode"] == MODE_WHOLE
        assert above["atlas"]["mode"] == MODE_SCOPED, (
            "the same repo produced the same mode on both sides of the "
            "threshold -- the switch is not reading the threshold")
        assert below["atlas"]["mode"] != above["atlas"]["mode"]

    def test_LOADBEARING_the_artifact_states_its_own_completeness(self, db_session, monkeypatch):
        """A scoped artifact that did not say so would be read as a whole
        graph, and every conclusion drawn from it would be wrong in a way
        nothing in the file reveals."""
        repo = _repo(db_session, n_files=6)

        monkeypatch.setattr(atlas_export, "WHOLE_GRAPH_MAX_FILES", 3)
        monkeypatch.setattr(atlas_export, "SCOPED_MAX_FILES", 3)
        art = export_atlas(db_session, repo.id)
        meta = art["atlas"]

        assert meta["complete"] is False
        assert meta["files_total"] == 6
        assert meta["files_included"] == 3
        assert len(art["nodes"]) == meta["files_included"], (
            "the stated count and the actual payload disagree -- the claim a "
            "consumer checks completeness against must be the true one")

    def test_scoping_keeps_the_best_ranked_files(self, db_session, monkeypatch):
        repo = _repo(db_session, n_files=6)
        monkeypatch.setattr(atlas_export, "WHOLE_GRAPH_MAX_FILES", 3)
        monkeypatch.setattr(atlas_export, "SCOPED_MAX_FILES", 3)
        art = export_atlas(db_session, repo.id)

        assert [n["p"] for n in art["nodes"]] == [
            "pkg/f0.py", "pkg/f1.py", "pkg/f2.py"]

    def test_scoped_edges_are_induced_with_no_dangling_endpoint(self, db_session, monkeypatch):
        """An edge pointing at a path the artifact does not contain is a
        reference a consumer cannot follow."""
        repo = _repo(db_session, n_files=6)
        monkeypatch.setattr(atlas_export, "WHOLE_GRAPH_MAX_FILES", 3)
        monkeypatch.setattr(atlas_export, "SCOPED_MAX_FILES", 3)
        art = export_atlas(db_session, repo.id)

        present = {n["p"] for n in art["nodes"]}
        for a, b in art["edges"]:
            assert a in present and b in present

    def test_choose_mode_is_inclusive_at_the_threshold(self):
        assert choose_mode(atlas_export.WHOLE_GRAPH_MAX_FILES) == MODE_WHOLE
        assert choose_mode(atlas_export.WHOLE_GRAPH_MAX_FILES + 1) == MODE_SCOPED

    def test_an_unknown_mode_override_raises(self, db_session):
        repo = _repo(db_session)
        with pytest.raises(ValueError):
            export_atlas(db_session, repo.id, mode="partial")


class TestUnresolvedEdgesAreCarried:
    """CANARY. `_build_graph` drops these; 1a keeps them; the artifact must
    still carry them or the whole point of 1a is lost at the last step."""

    def test_LOADBEARING_an_unresolved_import_reaches_the_artifact(self, db_session):
        repo = _repo(db_session)
        art = export_atlas(db_session, repo.id)

        assert art["unresolved_edges"] == [["pkg/f0.py", "requests"]]
        assert art["atlas"]["unresolved_edges_included"] == 1

    def test_LOADBEARING_they_survive_scoping(self, db_session, monkeypatch):
        repo = _repo(db_session, n_files=6)
        monkeypatch.setattr(atlas_export, "WHOLE_GRAPH_MAX_FILES", 3)
        monkeypatch.setattr(atlas_export, "SCOPED_MAX_FILES", 3)
        art = export_atlas(db_session, repo.id)

        assert art["unresolved_edges"] == [["pkg/f0.py", "requests"]], (
            "scoping dropped an unresolved import whose source IS in the "
            "artifact -- that fact is true regardless of how much was emitted")

    def test_resolved_and_unresolved_need_no_null_test_to_tell_apart(self, db_session):
        repo = _repo(db_session)
        art = export_atlas(db_session, repo.id)
        assert all(len(e) == 2 and e[1] for e in art["edges"])
        assert art["edges"] and art["unresolved_edges"]


class TestBoundaryIsTheOnlyReadPath:
    """CANARY, and the reason checkpoint 1a came first."""

    def test_LOADBEARING_stubbing_the_boundary_replaces_the_entire_artifact(
            self, db_session, monkeypatch):
        """If the emitter reads any table directly, real repo data survives a
        stubbed boundary and shows up alongside the fake."""
        repo = _repo(db_session)

        fake = RepoGraphT(
            repo_id=repo.id, repo_label="stub/only",
            nodes=[NodeT(path="STUB.py", language="python", size_bytes=1,
                         line_count=1, prior_category=None, fan_in=0, fan_out=0,
                         is_entry_point=True, seed_eligible=True,
                         reachable_from_entry=True, clusters={},
                         ranks=[RankT("legacy", 1.0, 1, None)])],
            edges=[], cycles=[], clusters=[])
        monkeypatch.setattr(atlas_export, "read_repo_graph",
                            lambda db, rid, **kw: fake)

        art = export_atlas(db_session, repo.id)

        assert [n["p"] for n in art["nodes"]] == ["STUB.py"], (
            "real file paths survived a stubbed boundary -- the emitter is "
            "reading tables directly and checkpoint 1a's single read path is "
            "already broken")
        assert art["atlas"]["repo"] == "stub/only"
        assert art["atlas"]["files_total"] == 1

    def test_the_emitter_source_contains_no_database_access(self):
        """A grep-level backstop for the case above: even a code path the tests
        do not exercise must not be able to reach the tables."""
        import pathlib
        src = pathlib.Path(atlas_export.__file__).read_text(encoding="utf-8")
        # Docstrings legitimately discuss these ideas; only CODE is checked.
        code = "\n".join(
            ln for ln in src.splitlines()
            if not ln.lstrip().startswith(("#", '"""', "*", "`")))
        for forbidden in ("db.execute", "text(", "SELECT ", "from app.db.models",
                          "session.query", ".query("):
            assert forbidden not in code, (
                f"emitter reaches the database directly via {forbidden!r}")

    def test_symbols_are_not_paid_for(self, db_session, monkeypatch):
        """The compact shape carries no symbols, so reading them would be
        paying for something the artifact discards."""
        seen = {}
        real = atlas_export.read_repo_graph
        monkeypatch.setattr(atlas_export, "read_repo_graph",
                            lambda db, rid, **kw: (seen.update(kw), real(db, rid, **kw))[1])
        repo = _repo(db_session)
        export_atlas(db_session, repo.id)
        assert seen.get("include_symbols") is False
