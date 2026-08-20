"""mark a codebase module orphaned by a re-clustering instead of deleting it

Revision ID: a1c9e37f4b82
Revises: f8a3c21d9b45
Create Date: 2026-08-17

A module's slug embeds its subsystem_id, and CodeSubsystem rows are replaced
wholesale on every clustering run. Modules are therefore matched to their
predecessors by shared file paths rather than by slug -- but a cluster can
genuinely dissolve, leaving a module that no longer corresponds to anything in
the repo while a user has study progress recorded against it.

Deleting it would cascade to its topics and take the topic_progress rows with
them: real study destroyed by a re-cluster the user did not ask for and cannot
see. This column marks such a module as kept-because-studied.

An orphan with NO progress is still deleted -- there is nothing to preserve,
and keeping it would accumulate dead rows on every re-cluster. So NULL here
does not mean "current"; it means "not being kept for its progress".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c9e37f4b82'
down_revision: Union[str, Sequence[str], None] = 'f8a3c21d9b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('code_orphaned_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.drop_column('code_orphaned_at')
