"""phase G1 move file-level signals off code_file_ranks

Revision ID: 6a601d21fa80
Revises: d2fb0eec7934
Create Date: 2026-08-07 18:01:21.141763

Diagnosed live on /repos/:id: fan_in, fan_out, is_entry_point, commit_count,
distinct_authors, days_since_last_change, and reduced_confidence were stored
once per (file, scorer) on code_file_ranks, with nothing forcing the copies
to agree -- the same file showed a real commit count under one scorer's row
and null under another's, because weighted_pagerank never computes history
at all. fan_in/fan_out/is_entry_point move to code_files (identical
regardless of scorer -- same resolved import graph, same entry_detection
call); reduced_confidence moves to repos (repo-wide: one git-log call per
rank run, not even file-level). code_file_ranks gains `rank`, the position
this migration backfills from current score order and every future rank run
stores directly, so /repos/:id ranking display never has to re-derive it
from a filtered or re-sorted view.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a601d21fa80'
down_revision: Union[str, Sequence[str], None] = 'd2fb0eec7934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Preference order for picking ONE (file, scorer) row's values to seed
# code_files with, when a file has more than one existing rank row:
# legacy/rrf actually compute history; weighted_pagerank never does, so it's
# the last resort, used only when it's the sole row a file has.
SCORER_PREFERENCE = ("legacy", "rrf", "weighted_pagerank")


def upgrade() -> None:
    # ---- 1. Add nullable destination columns ----
    with op.batch_alter_table("repos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reduced_confidence", sa.Boolean(), nullable=True))

    with op.batch_alter_table("code_files", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fan_in", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fan_out", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_entry_point", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("commit_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("distinct_authors", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("days_since_last_change", sa.Integer(), nullable=True))

    with op.batch_alter_table("code_file_ranks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rank", sa.Integer(), nullable=True))

    # ---- 2. Data migration -- must run before the source columns are dropped ----
    bind = op.get_bind()
    metadata = sa.MetaData()
    code_files = sa.Table("code_files", metadata, autoload_with=bind)
    code_file_ranks = sa.Table("code_file_ranks", metadata, autoload_with=bind)
    repos = sa.Table("repos", metadata, autoload_with=bind)

    all_rows = [dict(row) for row in bind.execute(sa.select(code_file_ranks)).mappings()]

    rows_by_file: dict = {}
    rows_by_repo: dict = {}
    rows_by_repo_scorer: dict = {}
    for row in all_rows:
        rows_by_file.setdefault(row["file_id"], []).append(row)
        rows_by_repo.setdefault(row["repo_id"], []).append(row)
        rows_by_repo_scorer.setdefault((row["repo_id"], row["scorer"]), []).append(row)

    # Disagreement check: every rank row for a given file is computed from
    # the same resolved import graph and the same entry_detection call, so
    # fan_in/fan_out/is_entry_point should be identical across all of a
    # file's rows regardless of scorer. A mismatch means two rows were
    # written at different times against different graph states -- exactly
    # the shape of the Phase F7 fan_in=0 incident. Dump full rows, not just
    # a flag, if this ever fires -- this is the first real evidence about
    # what happened, if it happened.
    disagreement_count = 0
    for file_id, rows in rows_by_file.items():
        shapes = {(r["fan_in"], r["fan_out"], r["is_entry_point"]) for r in rows}
        if len(shapes) > 1:
            disagreement_count += 1
            print(f"[6a601d21fa80] DISAGREEMENT on code_files.id={file_id} across its rank rows:")
            for r in rows:
                print(f"    {r}")
    print(f"[6a601d21fa80] {disagreement_count} file(s) had disagreeing fan_in/fan_out/is_entry_point across scorer rows.")

    # Backfill code_files from whichever row wins SCORER_PREFERENCE.
    weighted_pagerank_only_count = 0
    for file_id, rows in rows_by_file.items():
        by_scorer = {r["scorer"]: r for r in rows}
        chosen = next((by_scorer[s] for s in SCORER_PREFERENCE if s in by_scorer), None)
        if chosen is None:
            continue
        if set(by_scorer.keys()) == {"weighted_pagerank"}:
            weighted_pagerank_only_count += 1
        bind.execute(
            code_files.update().where(code_files.c.id == file_id).values(
                fan_in=chosen["fan_in"], fan_out=chosen["fan_out"], is_entry_point=chosen["is_entry_point"],
                commit_count=chosen["commit_count"], distinct_authors=chosen["distinct_authors"],
                days_since_last_change=chosen["days_since_last_change"],
            )
        )
    print(
        f"[6a601d21fa80] {weighted_pagerank_only_count} file(s) had ONLY a weighted_pagerank rank row -- "
        "history fields left null even if git history is actually available for that repo. "
        "A re-rank with legacy or rrf populates them; cheaper than a cleverer backfill."
    )

    # reduced_confidence is repo-wide: one value per repo, from whichever
    # row a repo has that actually computes history (weighted_pagerank
    # rows never set this meaningfully).
    for repo_id, rows in rows_by_repo.items():
        by_scorer = {r["scorer"]: r for r in rows}
        chosen = by_scorer.get("legacy") or by_scorer.get("rrf")
        if chosen is None:
            continue
        bind.execute(
            repos.update().where(repos.c.id == repo_id).values(reduced_confidence=chosen["reduced_confidence"])
        )

    # Backfill rank per (repo_id, scorer) group from current score order --
    # rank was never stored before this migration, only implicit in
    # whatever order a read-time `ORDER BY score DESC` produced.
    for (repo_id, scorer), rows in rows_by_repo_scorer.items():
        ordered = sorted(rows, key=lambda r: r["score"], reverse=True)
        for i, r in enumerate(ordered, start=1):
            bind.execute(code_file_ranks.update().where(code_file_ranks.c.id == r["id"]).values(rank=i))

    # ---- 3. Drop the now-migrated columns from code_file_ranks ----
    with op.batch_alter_table("code_file_ranks", schema=None) as batch_op:
        batch_op.drop_column("fan_in")
        batch_op.drop_column("fan_out")
        batch_op.drop_column("is_entry_point")
        batch_op.drop_column("commit_count")
        batch_op.drop_column("distinct_authors")
        batch_op.drop_column("days_since_last_change")
        batch_op.drop_column("reduced_confidence")


def downgrade() -> None:
    # Best-effort and lossy by construction: a file's single code_files row
    # gets copied back onto EVERY one of its rank rows, including
    # weighted_pagerank's -- which never had real history data of its own
    # to begin with, so this restores the pre-migration SHAPE, not
    # necessarily byte-identical pre-migration VALUES for that scorer.
    with op.batch_alter_table("code_file_ranks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fan_in", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fan_out", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_entry_point", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("commit_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("distinct_authors", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("days_since_last_change", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reduced_confidence", sa.Boolean(), nullable=True))

    bind = op.get_bind()
    metadata = sa.MetaData()
    code_files = sa.Table("code_files", metadata, autoload_with=bind)
    code_file_ranks = sa.Table("code_file_ranks", metadata, autoload_with=bind)
    repos = sa.Table("repos", metadata, autoload_with=bind)

    files_by_id = {row["id"]: row for row in bind.execute(sa.select(code_files)).mappings()}
    repos_by_id = {row["id"]: row for row in bind.execute(sa.select(repos)).mappings()}

    for rank_row in bind.execute(sa.select(code_file_ranks)).mappings():
        f = files_by_id.get(rank_row["file_id"])
        r = repos_by_id.get(rank_row["repo_id"])
        bind.execute(
            code_file_ranks.update().where(code_file_ranks.c.id == rank_row["id"]).values(
                fan_in=f["fan_in"] if f else None,
                fan_out=f["fan_out"] if f else None,
                is_entry_point=f["is_entry_point"] if f else None,
                commit_count=f["commit_count"] if f else None,
                distinct_authors=f["distinct_authors"] if f else None,
                days_since_last_change=f["days_since_last_change"] if f else None,
                reduced_confidence=r["reduced_confidence"] if r else None,
            )
        )

    with op.batch_alter_table("code_file_ranks", schema=None) as batch_op:
        batch_op.drop_column("rank")

    with op.batch_alter_table("code_files", schema=None) as batch_op:
        batch_op.drop_column("fan_in")
        batch_op.drop_column("fan_out")
        batch_op.drop_column("is_entry_point")
        batch_op.drop_column("commit_count")
        batch_op.drop_column("distinct_authors")
        batch_op.drop_column("days_since_last_change")

    with op.batch_alter_table("repos", schema=None) as batch_op:
        batch_op.drop_column("reduced_confidence")
