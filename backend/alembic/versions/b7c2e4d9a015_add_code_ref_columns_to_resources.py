"""add nullable code_ref columns to resources

Revision ID: b7c2e4d9a015
Revises: a4f1c9e07b52
Create Date: 2026-08-14 03:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c2e4d9a015'
down_revision: Union[str, Sequence[str], None] = 'a4f1c9e07b52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Five nullable columns so a resource CAN point at code. Nothing writes
    them yet and nothing reads them.

    Additive, reversible, unwired -- deliberately all three. Every column is
    nullable with no default, so every one of the 197 existing rows is
    unchanged and still valid; no existing column is altered; and no code path
    populates or consumes these, so no endpoint's output changes. `downgrade`
    drops exactly what `upgrade` added, leaving no data to reconcile.

    Why these five and not `file_path`: `resources.file_path` already exists and
    means a path to an UPLOADED file on this machine. A code reference is a
    different thing -- a location inside a registered repository -- and
    overloading the existing column would make "which kind of path is this?"
    unanswerable from the row.

    `commit_sha` is the one that is easy to leave out and shouldn't be. A code
    reference without a commit points at a moving target: the line numbers are
    only meaningful against the revision they were computed from, and a repo
    that is re-ingested a week later can invalidate them silently. Storing the
    SHA is what makes a stale reference detectable rather than merely wrong.

    No foreign key on repo_id, deliberately. Every FK in this schema is
    ON DELETE NO ACTION and nothing cascades, so a constrained repo_id would
    make repo deletion fail against a resource row rather than clean up after
    it -- and deleting a user's curated resource because a repo was evicted is
    the wrong outcome. Nullable and unconstrained means a deleted repo leaves a
    resource whose reference is dangling and detectably so.
    """
    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('code_repo_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('code_path', sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column('code_line_start', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('code_line_end', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('code_commit_sha', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Drops all five. Nothing reads them, so nothing breaks."""
    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.drop_column('code_commit_sha')
        batch_op.drop_column('code_line_end')
        batch_op.drop_column('code_line_start')
        batch_op.drop_column('code_path')
        batch_op.drop_column('code_repo_id')
