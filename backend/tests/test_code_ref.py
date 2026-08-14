"""Phase 4 groundwork: the code_ref constructor's invariants.

Every rule tested here exists because breaking it fails SILENTLY -- the
reference still renders and still looks authoritative. None of these is a
type check for its own sake.
"""
import pytest

from app.services.codebase.code_ref import CodeRef, InvalidCodeRef, is_stale, make_code_ref

VALID_SHA = "a" * 40
SHA256 = "b" * 64


def ref(**over):
    kw = dict(repo_id=1, path="pkg/mod.py", commit_sha=VALID_SHA)
    kw.update(over)
    return make_code_ref(**kw)


class TestTheShaRule:
    """The invariant most likely to be dropped as pedantic, and the one that
    decays fastest."""

    def test_LOADBEARING_a_reference_without_a_sha_is_refused(self):
        with pytest.raises(InvalidCodeRef, match="stale"):
            make_code_ref(repo_id=1, path="a.py", commit_sha="", line_start=1, line_end=2)

    def test_LOADBEARING_a_branch_name_is_not_a_commit(self):
        # "main" and "HEAD" are the two things most likely to be passed by
        # mistake, and neither is a fixed point.
        for not_a_sha in ("main", "HEAD", "v1.2.3", "a" * 39, "g" * 40):
            with pytest.raises(InvalidCodeRef):
                make_code_ref(repo_id=1, path="a.py", commit_sha=not_a_sha)

    def test_accepts_sha1_and_sha256_and_normalises_case(self):
        assert ref(commit_sha=VALID_SHA.upper()).commit_sha == VALID_SHA
        assert ref(commit_sha=SHA256).commit_sha == SHA256


class TestLineRanges:
    def test_LOADBEARING_one_line_without_the_other_is_refused(self):
        # A half-set range cannot be told apart from a range that failed to
        # compute, so both are refused rather than one being inferred.
        with pytest.raises(InvalidCodeRef, match="both"):
            ref(line_start=5)
        with pytest.raises(InvalidCodeRef, match="both"):
            ref(line_end=5)

    def test_LOADBEARING_a_reversed_range_is_refused(self):
        with pytest.raises(InvalidCodeRef, match="before"):
            ref(line_start=40, line_end=12)

    def test_a_whole_file_reference_is_valid_and_says_so(self):
        r = ref()
        assert r.is_whole_file
        assert r.describe() == f"pkg/mod.py @ {VALID_SHA[:7]}"

    def test_a_single_line_reads_as_one_number(self):
        assert ref(line_start=7, line_end=7).describe().startswith("pkg/mod.py:7 @")

    def test_zero_and_negative_lines_are_refused(self):
        for pair in ((0, 5), (1, 0), (-3, -1)):
            with pytest.raises(InvalidCodeRef, match="1-based"):
                ref(line_start=pair[0], line_end=pair[1])


class TestPaths:
    def test_LOADBEARING_an_absolute_path_is_refused(self):
        for absolute in ("/etc/passwd", "C:/Users/x/a.py", "D:\\repo\\a.py"):
            with pytest.raises(InvalidCodeRef):
                ref(path=absolute)

    def test_LOADBEARING_dotdot_is_refused(self):
        with pytest.raises(InvalidCodeRef, match=r"\.\."):
            ref(path="pkg/../../etc/passwd")

    def test_backslashes_are_refused_because_CodeFile_path_uses_forward_slashes(self):
        with pytest.raises(InvalidCodeRef, match="forward slashes"):
            ref(path="pkg\\mod.py")

    def test_a_dotdot_inside_a_filename_is_fine(self):
        # "..' as a path SEGMENT is the escape; two dots in a name are not.
        assert ref(path="pkg/weird..name.py").path == "pkg/weird..name.py"

    def test_empty_path_is_refused(self):
        with pytest.raises(InvalidCodeRef, match="required"):
            ref(path="   ")


class TestColumnMapping:
    def test_to_columns_matches_the_migration(self):
        cols = ref(line_start=1, line_end=9).to_columns()
        assert set(cols) == {
            "code_repo_id", "code_path", "code_line_start",
            "code_line_end", "code_commit_sha",
        }
        assert cols["code_line_start"] == 1 and cols["code_line_end"] == 9


class TestStaleness:
    def test_a_different_sha_is_stale(self):
        assert is_stale(ref(), "c" * 40) is True

    def test_the_same_sha_is_not(self):
        assert is_stale(ref(), VALID_SHA.upper()) is False

    def test_LOADBEARING_an_unknown_current_sha_is_not_reported_as_stale(self):
        # Exclude-don't-zero: an unknown answer must not be reported as a
        # positive finding.
        assert is_stale(ref(), None) is False
        assert is_stale(ref(), "") is False
