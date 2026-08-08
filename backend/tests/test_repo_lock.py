"""Phase E2.3 incident follow-up: per-repo advisory lock. Pure unit tests
for the lock mechanism itself; ingest_repo/rank_repo*'s actual use of it is
covered in test_ingest.py / test_ranking.py.
"""
import pytest

from app.services.codebase.repo_lock import RepoBusyError, repo_lock


class TestRepoLock:
    def test_lock_acquired_and_released_normally(self):
        with repo_lock(1, "test"):
            pass  # must not raise

    def test_second_acquire_for_same_repo_raises_while_held(self):
        with repo_lock(2, "ingest"):
            with pytest.raises(RepoBusyError):
                with repo_lock(2, "rank"):
                    pass

    def test_lock_released_after_context_exits_normally(self):
        with repo_lock(3, "ingest"):
            pass
        with repo_lock(3, "rank"):  # must succeed -- prior lock was released
            pass

    def test_lock_released_even_when_body_raises(self):
        with pytest.raises(ValueError):
            with repo_lock(4, "ingest"):
                raise ValueError("boom")
        with repo_lock(4, "rank"):  # must still succeed -- released in `finally`
            pass

    def test_different_repo_ids_do_not_block_each_other(self):
        with repo_lock(5, "ingest"):
            with repo_lock(6, "rank"):  # different repo -- must not raise
                pass

    def test_busy_error_message_names_repo_and_operation(self):
        with repo_lock(7, "ingest"):
            with pytest.raises(RepoBusyError, match=r"[Rr]epo 7.*rank"):
                with repo_lock(7, "rank"):
                    pass
