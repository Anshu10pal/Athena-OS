"""Phase E2.1: Python root discovery. Pure-function tests -- marker/structural
nomination read real files on disk (tmp_path); scoring takes plain data, no
DB, reusing resolve_imports.resolve_python_import exactly as the real
resolution pass does (verification, not pattern-matching).
"""
from pathlib import Path

from app.services.codebase.root_discovery import (
    find_marker_candidate_roots,
    find_structural_candidate_roots,
    is_stdlib_specifier,
    load_root_discovery_config,
    nearest_promoted_root,
    partition_unresolved_specifiers,
    promote_roots,
    root_depth,
    score_candidate_roots,
)
from tests.fixtures.known_external_python_specifiers import (
    REPO_1_KNOWN_EXTERNAL_SPECIFIERS,
    REPO_2_KNOWN_EXTERNAL_SPECIFIERS,
)


def _write(path: Path, content: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestFindMarkerCandidateRoots:
    def test_repo_root_always_a_candidate(self, tmp_path):
        assert "" in find_marker_candidate_roots(tmp_path)

    def test_requirements_txt_nominates_its_directory(self, tmp_path):
        _write(tmp_path / "backend" / "requirements.txt")
        candidates = find_marker_candidate_roots(tmp_path)
        assert "backend" in candidates

    def test_pyproject_toml_nominates_its_directory(self, tmp_path):
        _write(tmp_path / "backend" / "pyproject.toml")
        assert "backend" in find_marker_candidate_roots(tmp_path)

    def test_setup_py_nominates_its_directory(self, tmp_path):
        _write(tmp_path / "lib" / "setup.py")
        assert "lib" in find_marker_candidate_roots(tmp_path)

    def test_pipfile_nominates_its_directory(self, tmp_path):
        _write(tmp_path / "svc" / "Pipfile")
        assert "svc" in find_marker_candidate_roots(tmp_path)

    def test_ignored_directories_are_skipped(self, tmp_path):
        _write(tmp_path / "node_modules" / "somepkg" / "requirements.txt")
        candidates = find_marker_candidate_roots(tmp_path)
        assert "node_modules/somepkg" not in candidates

    def test_marker_at_repo_root_does_not_duplicate_root_candidate(self, tmp_path):
        _write(tmp_path / "requirements.txt")
        candidates = find_marker_candidate_roots(tmp_path)
        assert candidates == {""}

    def test_config_search_root_defaults_to_repo_root_unchanged(self, tmp_path):
        # Backward compatibility: omitting config_search_root must behave
        # exactly as before -- this is the same assertion every prior test
        # in this class already makes, restated explicitly as its own test
        # so a future change to the default can't silently regress it.
        _write(tmp_path / "backend" / "requirements.txt")
        assert find_marker_candidate_roots(tmp_path) == find_marker_candidate_roots(tmp_path, config_search_root=tmp_path)

    def test_marker_above_repo_root_is_found_via_config_search_root(self, tmp_path):
        # config_search_root/pyproject.toml lives ABOVE repo_root
        # (config_search_root/backend) -- the exact source_root-scoped
        # miss confirmed in docs/external-validation-eslint.md's Round 2.
        _write(tmp_path / "pyproject.toml")
        repo_root = tmp_path / "backend"
        repo_root.mkdir()
        candidates = find_marker_candidate_roots(repo_root, config_search_root=tmp_path)
        # The marker itself sits OUTSIDE repo_root's own subtree, so it
        # has no valid "relative to repo_root" representation -- correctly
        # excluded, not silently mis-mapped to "" or some wrong path.
        assert candidates == {""}

    def test_marker_above_repo_root_never_produces_a_false_candidate(self, tmp_path):
        # Same setup, but with a SECOND marker genuinely inside repo_root
        # -- proves the above-root marker is cleanly ignored rather than
        # somehow corrupting or duplicating a real, valid candidate.
        _write(tmp_path / "pyproject.toml")
        repo_root = tmp_path / "backend"
        _write(repo_root / "services" / "requirements.txt")
        candidates = find_marker_candidate_roots(repo_root, config_search_root=tmp_path)
        assert candidates == {"", "services"}

    def test_config_search_root_widening_matches_repo_root_only_scan_for_in_scope_markers(self, tmp_path):
        # States plainly, as a test, the module docstring's own honest
        # claim: for anything actually inside repo_root's subtree,
        # widening the search changes nothing -- scanning from an
        # ancestor and filtering down finds the identical set scanning
        # repo_root directly would.
        repo_root = tmp_path / "backend"
        _write(repo_root / "svc" / "Pipfile")
        widened = find_marker_candidate_roots(repo_root, config_search_root=tmp_path)
        unwidened = find_marker_candidate_roots(repo_root)
        assert widened == unwidened == {"", "svc"}


class TestFindStructuralCandidateRoots:
    def test_top_level_package_nominates_repo_root(self):
        python_files = {"app/__init__.py", "app/main.py"}
        candidates = find_structural_candidate_roots(python_files, unresolved_specifiers=[])
        assert "" in candidates

    def test_nested_package_nominates_its_container(self):
        python_files = {"backend/app/__init__.py", "backend/app/main.py"}
        candidates = find_structural_candidate_roots(python_files, unresolved_specifiers=[])
        assert "backend" in candidates

    def test_bare_specifier_nominates_directory_containing_matching_module(self):
        python_files = {"backend/crud.py", "backend/schemas.py"}
        candidates = find_structural_candidate_roots(python_files, unresolved_specifiers=["crud"])
        assert "backend" in candidates

    def test_dotted_specifier_uses_first_component_only(self):
        python_files = {"backend/app.py"}
        candidates = find_structural_candidate_roots(python_files, unresolved_specifiers=["app.db.models"])
        assert "backend" in candidates

    def test_relative_specifier_contributes_no_bare_module_nomination(self):
        python_files = {"backend/helper.py"}
        # a relative specifier's "first component" would be "" after
        # stripping dots -- must not spuriously match an unrelated module
        candidates = find_structural_candidate_roots(python_files, unresolved_specifiers=[".helper"])
        assert "backend" not in candidates

    def test_no_matching_module_nominates_nothing(self):
        python_files = {"backend/crud.py"}
        candidates = find_structural_candidate_roots(python_files, unresolved_specifiers=["nonexistent"])
        assert candidates == set()


class TestScoreCandidateRoots:
    def test_verified_resolution_credited(self):
        all_paths = {"backend/app/db/models.py"}
        rows = [{"from_file": "backend/app/main.py", "raw_specifier": "app.db.models", "name": None}]
        scores = score_candidate_roots({"backend"}, rows, all_paths)
        assert scores["backend"]["score"] == 1
        assert scores["backend"]["percentage"] == 1.0
        assert scores["backend"]["specifiers"] == [("app.db.models", "backend/app/db/models.py", "backend/app/main.py")]

    def test_unverified_pattern_match_is_not_credited(self):
        # "app.db.models" under root "backend" WOULD imply backend/app/db/models.py,
        # but that file does NOT exist -- must not be credited on pattern alone.
        all_paths = {"backend/app/other.py"}
        rows = [{"from_file": "backend/app/main.py", "raw_specifier": "app.db.models", "name": None}]
        scores = score_candidate_roots({"backend"}, rows, all_paths)
        assert scores["backend"]["score"] == 0

    def test_relative_specifiers_excluded_from_denominator(self):
        all_paths = {"backend/app/db/models.py", "backend/app/sibling.py"}
        rows = [
            {"from_file": "backend/app/main.py", "raw_specifier": "app.db.models", "name": None},
            {"from_file": "backend/app/main.py", "raw_specifier": ".sibling", "name": None},
        ]
        scores = score_candidate_roots({"backend"}, rows, all_paths)
        assert scores["backend"]["score"] == 1
        assert scores["backend"]["percentage"] == 1.0  # denominator is 1 (relative excluded), not 2

    def test_overlapping_roots_deduplicated_by_target_deepest_wins(self):
        # Same target file reachable from both "" (bare repo root, via a
        # specifier that happens to spell out the full nested path) and
        # "backend" (via the natural absolute specifier) -- only the
        # deeper root ("backend") should keep credit for that file.
        all_paths = {"backend/app/db/models.py"}
        rows = [
            {"from_file": "backend/app/main.py", "raw_specifier": "app.db.models", "name": None},
            {"from_file": "other/caller.py", "raw_specifier": "backend.app.db.models", "name": None},
        ]
        scores = score_candidate_roots({"", "backend"}, rows, all_paths)
        assert scores["backend"]["score"] == 1
        assert scores[""]["score"] == 0

    def test_score_zero_when_no_unresolved_rows(self):
        scores = score_candidate_roots({"backend"}, [], {"backend/app.py"})
        assert scores["backend"]["score"] == 0
        assert scores["backend"]["percentage"] == 0.0


class TestIsStdlibSpecifier:
    def test_known_stdlib_module_detected(self):
        assert is_stdlib_specifier("json") is True
        assert is_stdlib_specifier("typing") is True

    def test_dotted_stdlib_submodule_detected_by_first_component(self):
        assert is_stdlib_specifier("logging.config") is True

    def test_third_party_package_not_detected_as_stdlib(self):
        assert is_stdlib_specifier("fastapi") is False
        assert is_stdlib_specifier("sqlalchemy.orm") is False

    def test_internal_looking_specifier_not_detected_as_stdlib(self):
        assert is_stdlib_specifier("app.db.models") is False

    def test_known_external_fixtures_never_misclassified_as_stdlib(self):
        # Guards the ground-truth fixture's own integrity: nothing on either
        # hand-verified external list should ever look like stdlib -- if it
        # did, the fixture's premise (100% of NON-stdlib unexplained
        # specifiers are third-party) would be wrong from the start.
        for spec in REPO_1_KNOWN_EXTERNAL_SPECIFIERS + REPO_2_KNOWN_EXTERNAL_SPECIFIERS:
            assert not is_stdlib_specifier(spec), f"{spec} is classified as stdlib, contradicting the ground truth fixture"


class TestPartitionUnresolvedSpecifiers:
    def test_stdlib_rows_separated_from_not_yet_classified(self):
        rows = [
            {"from_file": "a.py", "raw_specifier": "json", "name": None},
            {"from_file": "b.py", "raw_specifier": "app.db.models", "name": None},
            {"from_file": "c.py", "raw_specifier": "fastapi", "name": None},
        ]
        partition = partition_unresolved_specifiers(rows)
        assert [r["raw_specifier"] for r in partition["stdlib"]] == ["json"]
        assert {r["raw_specifier"] for r in partition["not_yet_classified"]} == {"app.db.models", "fastapi"}

    def test_empty_input_gives_empty_buckets(self):
        partition = partition_unresolved_specifiers([])
        assert partition == {"stdlib": [], "not_yet_classified": []}


class TestNearestPromotedRoot:
    def test_deepest_ancestor_root_wins(self):
        promoted = {"backend", "backend/app"}
        assert nearest_promoted_root("backend/app/db/models.py", promoted) == "backend/app"

    def test_shallower_root_used_when_no_deeper_one_is_an_ancestor(self):
        promoted = {"backend", "backend/app"}
        assert nearest_promoted_root("backend/scripts/validate.py", promoted) == "backend"

    def test_repo_root_promoted_governs_everything_not_covered_by_a_deeper_root(self):
        promoted = {"", "backend/app"}
        assert nearest_promoted_root("other/standalone.py", promoted) == ""

    def test_none_when_no_promoted_root_is_an_ancestor(self):
        promoted = {"backend/app"}
        assert nearest_promoted_root("voice_listener/wake_word.py", promoted) is None

    def test_none_when_no_roots_promoted_at_all(self):
        assert nearest_promoted_root("main.py", set()) is None

    def test_sibling_directory_with_similar_name_not_treated_as_ancestor(self):
        promoted = {"backend"}
        assert nearest_promoted_root("backend-tools/script.py", promoted) is None


class TestRootDepth:
    def test_repo_root_is_shallowest(self):
        assert root_depth("") < root_depth("backend")

    def test_more_segments_is_deeper(self):
        assert root_depth("backend/app") > root_depth("backend")

    def test_longer_string_breaks_ties_at_the_same_segment_count(self):
        assert root_depth("backend-extra") > root_depth("backend")


class TestPromoteRoots:
    def test_promoted_when_both_floors_cleared(self):
        scores = {"backend": {"score": 10, "percentage": 0.5, "specifiers": []}}
        assert promote_roots(scores, relative_floor=0.05, absolute_floor=3) == {"backend"}

    def test_not_promoted_below_absolute_floor_even_with_high_percentage(self):
        # 2 out of 2 unresolved specifiers is 100%, but only 2 specifiers --
        # could be coincidence.
        scores = {"backend": {"score": 2, "percentage": 1.0, "specifiers": []}}
        assert promote_roots(scores, relative_floor=0.05, absolute_floor=3) == set()

    def test_not_promoted_below_relative_floor_even_with_high_absolute_count(self):
        scores = {"backend": {"score": 10, "percentage": 0.01, "specifiers": []}}
        assert promote_roots(scores, relative_floor=0.05, absolute_floor=3) == set()

    def test_defaults_to_config_when_floors_omitted(self):
        scores = {"backend": {"score": 3, "percentage": 0.05, "specifiers": []}}
        config = load_root_discovery_config()
        expected = config["relative_floor"] <= 0.05 and config["absolute_floor"] <= 3
        assert (promote_roots(scores) == {"backend"}) == expected


class TestLoadRootDiscoveryConfig:
    def test_default_floors_when_no_config_file(self):
        config = load_root_discovery_config()
        assert "relative_floor" in config
        assert "absolute_floor" in config


class TestRealisticFixtures:
    """The two structural test cases from the E2 brief: repo 1's nested
    package layout (needs a marker OR a package parent to nominate backend/)
    and repo 2's flat, marker-less app (needs the bare-specifier structural
    nomination -- nothing else would ever find its root)."""

    def test_nested_package_repo_promotes_backend(self, tmp_path):
        _write(tmp_path / "backend" / "requirements.txt")
        python_files = {
            "backend/app/__init__.py",
            "backend/app/main.py",
            "backend/app/db/__init__.py",
            "backend/app/db/models.py",
        }
        marker_candidates = find_marker_candidate_roots(tmp_path)
        structural_candidates = find_structural_candidate_roots(python_files, ["app.db.models"])
        candidates = marker_candidates | structural_candidates
        assert "backend" in candidates

        rows = [{"from_file": "backend/app/main.py", "raw_specifier": "app.db.models", "name": None}]
        scores = score_candidate_roots(candidates, rows, python_files)
        assert promote_roots(scores, relative_floor=0.05, absolute_floor=1) == {"backend"}

    def test_flat_marker_less_repo_promotes_its_root_via_structural_nomination_only(self, tmp_path):
        # no requirements.txt anywhere -- marker nomination alone would only
        # ever offer the bare repo root as a fallback candidate, and that's
        # NOT where these modules live.
        python_files = {"backend/crud.py", "backend/schemas.py", "backend/auth.py"}
        unresolved = ["crud", "schemas", "auth"]

        marker_candidates = find_marker_candidate_roots(tmp_path)
        assert marker_candidates == {""}  # confirms markers alone find nothing useful here

        structural_candidates = find_structural_candidate_roots(python_files, unresolved)
        assert "backend" in structural_candidates

        candidates = marker_candidates | structural_candidates
        rows = [
            {"from_file": "other/caller.py", "raw_specifier": "crud", "name": None},
            {"from_file": "other/caller.py", "raw_specifier": "schemas", "name": None},
            {"from_file": "other/caller.py", "raw_specifier": "auth", "name": None},
        ]
        scores = score_candidate_roots(candidates, rows, python_files)
        assert promote_roots(scores, relative_floor=0.05, absolute_floor=3) == {"backend"}
