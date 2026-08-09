"""Migration/model parity.

The rest of this suite builds its schema from the models via `create_all`, so
a column that exists on a model but was never migrated is **invisible to every
other test** -- exactly how `evidence_complete` -> `inputs_complete` reached a
live 500 with a green test run behind it.

This walks the real migration chain against a scratch database and compares
the result to the models, which is the only place that divergence can be
caught before deployment.
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import settings
from app.db.database import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]


# Captured at import, BEFORE any monkeypatching, so the guard below always has
# the real configured value to compare against.
CONFIGURED_DEV_URL = settings.DATABASE_URL


def assert_isolated(expected_scratch_url: str) -> None:
    """Refuse to run migrations unless `alembic/env.py` will read the scratch
    URL. Extracted so the guard itself is directly testable -- an inline
    assertion can only be tested by copy-pasting it, which tests the copy.

    Checks the value env.py ACTUALLY reads (`settings.DATABASE_URL`), not the
    Config option it overwrites and ignores.
    """
    if settings.DATABASE_URL != expected_scratch_url:
        raise AssertionError(
            "settings.DATABASE_URL was not redirected to the scratch database; "
            "alembic/env.py would migrate the configured database instead "
            f"(reads {settings.DATABASE_URL!r}, expected {expected_scratch_url!r})"
        )
    if settings.DATABASE_URL == CONFIGURED_DEV_URL:
        raise AssertionError(
            f"refusing to run migrations against the configured development "
            f"URL ({CONFIGURED_DEV_URL!r})"
        )


def _migrated_inspector(tmp_path, monkeypatch):
    """Run the real migration chain against a scratch DB.

    `alembic/env.py` overwrites `sqlalchemy.url` from `settings.DATABASE_URL`,
    so setting it on the Config alone is silently ignored -- the first version
    of this helper did exactly that and ran migrations against the developer's
    LIVE database. It was a no-op there only by luck (that DB was already at
    head); a chain with any unapplied revision would have mutated real data.

    The assertions below exist so a future env.py change cannot recreate that
    incident silently. They deliberately check the value env.py actually reads,
    not the Config option it ignores.
    """
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setattr(settings, "DATABASE_URL", url, raising=False)
    assert_isolated(url)

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    # Guard 2: migrations demonstrably landed HERE. If env.py ever stops
    # honouring settings, the scratch file has no alembic_version and this
    # fails loudly instead of the suite quietly passing while the real
    # database was the one that moved.
    assert db_path.exists(), "migrations did not create the scratch database"
    engine = create_engine(url)
    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names(), (
        "scratch database has no alembic_version table -- the migration run "
        "targeted some other database"
    )
    with engine.connect() as conn:
        stamped = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()
    assert stamped, "scratch database was never stamped with a revision"
    return inspector


# Only the tables this phase owns. The rest of the schema carries known,
# documented SQLite drift from before migrations were kept scoped, and
# asserting over all of it would fail for reasons unrelated to code health.
CODE_HEALTH_TABLES = ("code_health_snapshots", "code_file_health", "code_files")


class TestMigrationsMatchModels:
    def test_code_health_columns_exist_after_a_real_migration_run(self, tmp_path, monkeypatch):
        inspector = _migrated_inspector(tmp_path, monkeypatch)
        for table in CODE_HEALTH_TABLES:
            assert table in inspector.get_table_names(), f"{table} missing after upgrade head"
            migrated = {c["name"] for c in inspector.get_columns(table)}
            declared = {c.name for c in Base.metadata.tables[table].columns}
            missing = declared - migrated
            assert not missing, (
                f"{table}: columns on the model but not in any migration: {sorted(missing)}. "
                "create_all-based tests cannot see this."
            )

    def test_the_renamed_column_is_the_new_name_only(self, tmp_path, monkeypatch):
        inspector = _migrated_inspector(tmp_path, monkeypatch)
        columns = {c["name"] for c in inspector.get_columns("code_health_snapshots")}
        assert "inputs_complete" in columns
        assert "evidence_complete" not in columns

    def test_source_fingerprint_survived_the_chain(self, tmp_path, monkeypatch):
        # Identity for a dirty working tree depends on it, so its absence
        # would silently degrade idempotency to head_sha + dirty.
        inspector = _migrated_inspector(tmp_path, monkeypatch)
        columns = {c["name"] for c in inspector.get_columns("code_health_snapshots")}
        assert "source_fingerprint" in columns


class TestMigrationTestIsolation:
    """The guard itself is load-bearing: the first version of this file ran
    `upgrade head` against the developer's live database. These pin the
    isolation so a future env.py change cannot recreate that silently."""

    def test_the_scratch_url_is_never_the_configured_development_url(self, tmp_path, monkeypatch):
        _migrated_inspector(tmp_path, monkeypatch)
        assert settings.DATABASE_URL != CONFIGURED_DEV_URL
        assert str(tmp_path.as_posix()) in settings.DATABASE_URL

    def test_the_guard_refuses_when_settings_still_points_at_the_dev_database(
            self, tmp_path, monkeypatch):
        # The exact regression that caused the incident: settings is NOT
        # redirected, so env.py would target the live database. The guard must
        # refuse before `command.upgrade` is ever reached.
        monkeypatch.setattr(settings, "DATABASE_URL", CONFIGURED_DEV_URL, raising=False)
        scratch = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
        with pytest.raises(AssertionError, match="was not redirected"):
            assert_isolated(scratch)

    def test_the_guard_refuses_if_the_scratch_url_somehow_equals_the_dev_url(
            self, monkeypatch):
        # Belt-and-braces: even if a caller passed the dev URL as its
        # "scratch" path, the second check still refuses.
        monkeypatch.setattr(settings, "DATABASE_URL", CONFIGURED_DEV_URL, raising=False)
        with pytest.raises(AssertionError, match="refusing to run migrations"):
            assert_isolated(CONFIGURED_DEV_URL)

    def test_the_guard_passes_only_for_a_real_scratch_path(self, tmp_path, monkeypatch):
        scratch = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
        monkeypatch.setattr(settings, "DATABASE_URL", scratch, raising=False)
        assert_isolated(scratch)  # must not raise

    def test_the_development_database_is_left_untouched(self, tmp_path, monkeypatch):
        # Read-only proof: run the chain on a scratch DB and confirm the
        # configured database's revision is unchanged by it.
        dev_path = CONFIGURED_DEV_URL.replace("sqlite:///", "").replace("sqlite://", "")
        dev_file = (BACKEND_ROOT / dev_path.lstrip("./")).resolve()
        if not dev_file.exists():
            pytest.skip("configured development database not present in this environment")

        before = dev_file.stat().st_mtime_ns
        _migrated_inspector(tmp_path, monkeypatch)
        assert dev_file.stat().st_mtime_ns == before, (
            "the configured development database was modified by a migration test"
        )
