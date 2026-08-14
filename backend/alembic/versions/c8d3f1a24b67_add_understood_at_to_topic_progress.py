"""add nullable understood_at to topic_progress

Revision ID: c8d3f1a24b67
Revises: b7c2e4d9a015
Create Date: 2026-08-14 04:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d3f1a24b67'
down_revision: Union[str, Sequence[str], None] = 'b7c2e4d9a015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """`understood_at` beside `completed_at`, nullable, nothing written yet.

    `topic_progress` is binary and terminal today: one row, one NOT NULL
    `completed_at`, no state and no partial. That records "this was marked
    done" and cannot express "this was read but not understood" -- which is the
    distinction between a comprehension tool and a checklist.

    Nullable and additive rather than a state enum, deliberately. An enum would
    require deciding what each of the 14 existing rows means and writing that
    decision into them; this leaves every existing row untouched and
    `completed_at` meaning exactly what it meant. NULL here reads as "not
    claimed", which is the honest value for every row that predates the column
    -- the same exclude-don't-zero reasoning as `files_partially_na`, where a
    backfilled 0 would have been a confident wrong answer.

    Nothing reads or writes it. `downgrade` drops exactly this column.
    """
    with op.batch_alter_table('topic_progress', schema=None) as batch_op:
        batch_op.add_column(sa.Column('understood_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('topic_progress', schema=None) as batch_op:
        batch_op.drop_column('understood_at')
