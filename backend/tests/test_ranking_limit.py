"""Phase 8 checkpoint 3b-3 (D13) -- the /ranking `limit` parameter.

The LOAD-BEARING test here is the first one: omitting `limit` must reproduce
today's behaviour exactly. This endpoint has existing callers (RepoDetail's
`loadRanking`) and the parameter exists only so a top-N starting list does not
have to pull 2.85 MB.
"""
import pytest

import app.api.repos as R
from app.db.database import SessionLocal
from app.db.models import CodeFile

RID = 6


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


def _has_repo(db):
    return db.query(CodeFile).filter(CodeFile.repo_id == RID).first() is not None


def test_LOADBEARING_omitting_limit_is_byte_for_byte_the_old_behaviour(db):
    """Canary for the additive claim. If this ever differs, an existing caller
    changed behaviour without asking."""
    if not _has_repo(db):
        pytest.skip("superset ingest (repo 6) not present")
    d = R.get_ranking(RID, db=db, user=None)
    assert d["limit"] is None
    assert d["truncated"] is False
    assert len(d["files"]) == d["total_before_limit"]
    assert len(d["files"]) == 6584
    # the pre-existing keys are untouched
    assert set(d) >= {"scorer", "reduced_confidence", "files"}


def test_limit_truncates_after_ordering_not_before(db):
    """A top-N that sliced before ordering would return N arbitrary files under
    a name promising the N that matter."""
    if not _has_repo(db):
        pytest.skip("superset ingest (repo 6) not present")
    full = R.get_ranking(RID, db=db, user=None)["files"]
    top = R.get_ranking(RID, limit=10, db=db, user=None)
    assert len(top["files"]) == 10
    assert top["total_before_limit"] == 6584
    assert top["truncated"] is True
    # exactly the first ten of the ordered list, in order
    assert [f["file_id"] for f in top["files"]] == [f["file_id"] for f in full[:10]]
    assert [f["rank"] for f in top["files"]] == list(range(1, 11))


def test_a_truncated_response_is_detectable_by_its_consumer(db):
    """total_before_limit + truncated, so 10-of-6,584 cannot be mistaken for a
    repo with 10 files."""
    if not _has_repo(db):
        pytest.skip("superset ingest (repo 6) not present")
    d = R.get_ranking(RID, limit=3, db=db, user=None)
    assert d["truncated"] is True
    assert d["total_before_limit"] > len(d["files"])


def test_limit_larger_than_the_repo_is_not_truncation(db):
    if not _has_repo(db):
        pytest.skip("superset ingest (repo 6) not present")
    d = R.get_ranking(RID, limit=99999, db=db, user=None)
    assert len(d["files"]) == 6584
    assert d["truncated"] is False


def test_limit_zero_returns_nothing_and_says_so(db):
    """0 is a real answer, not a synonym for absent -- `None` means uncapped."""
    if not _has_repo(db):
        pytest.skip("superset ingest (repo 6) not present")
    d = R.get_ranking(RID, limit=0, db=db, user=None)
    assert d["files"] == []
    assert d["truncated"] is True
    assert d["total_before_limit"] == 6584


def test_the_empty_state_needs_a_LOW_connectivity_file_too(db):
    """D23's premise, pinned as a test.

    Rank ordering surfaces hubs -- superset/__init__.py and utils/core.py, the
    flattering end of a 0.93x-293x spread -- by a mechanism that looks neutral.
    scripts/__init__.py (0 connections, 0.994x) is rank 2,449 and would NEVER
    appear in a top-N list. A starting-point list that can only reach hubs
    misrepresents the feature by construction.
    """
    if not _has_repo(db):
        pytest.skip("superset ingest (repo 6) not present")
    top10 = R.get_ranking(RID, limit=10, db=db, user=None)["files"]
    paths = [f["path"] for f in top10]
    assert "scripts/__init__.py" not in paths
    floor = db.query(CodeFile).filter(
        CodeFile.repo_id == RID, CodeFile.path == "scripts/__init__.py").first()
    full = R.get_ranking(RID, db=db, user=None)["files"]
    floor_rank = next(f["rank"] for f in full if f["file_id"] == floor.id)
    assert floor_rank > 100, f"floor file ranks {floor_rank} -- unreachable by top-N"
