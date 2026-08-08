"""add code_file_ranks scorer column and widen unique constraint

Revision ID: 2e4f4b743bea
Revises: 74e855f74660
Create Date: 2026-08-06 21:24:19.838589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2e4f4b743bea'
down_revision: Union[str, Sequence[str], None] = '74e855f74660'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default required: code_file_ranks already has rows, scorer is
    # NOT NULL. Existing rows are all from the legacy scorer, so 'legacy' is
    # not just a safe placeholder here -- it's actually correct.
    # The unique constraint widens from (file_id) alone to (file_id, scorer)
    # so a second scorer (Phase F3's weighted_pagerank) can have its own row
    # per file without colliding with the legacy scorer's row for that file.
    with op.batch_alter_table('code_file_ranks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scorer', sa.String(length=30), nullable=False, server_default='legacy'))
        batch_op.drop_constraint('uq_code_file_rank_file', type_='unique')
        batch_op.create_unique_constraint('uq_code_file_rank_file_scorer', ['file_id', 'scorer'])


def downgrade() -> None:
    with op.batch_alter_table('code_file_ranks', schema=None) as batch_op:
        batch_op.drop_constraint('uq_code_file_rank_file_scorer', type_='unique')
        batch_op.create_unique_constraint('uq_code_file_rank_file', ['file_id'])
        batch_op.drop_column('scorer')
