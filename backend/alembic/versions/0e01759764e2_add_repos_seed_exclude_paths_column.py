"""add repos seed_exclude_paths column

Revision ID: 0e01759764e2
Revises: 2e4f4b743bea
Create Date: 2026-08-07 00:04:36.377047

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0e01759764e2'
down_revision: Union[str, Sequence[str], None] = '2e4f4b743bea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default required: repos already has rows, seed_exclude_paths is
    # NOT NULL. '[]' (empty JSON array) is correct for every existing row --
    # this column didn't exist before, so no repo could have had a
    # meaningful override yet.
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seed_exclude_paths', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('seed_exclude_paths')
