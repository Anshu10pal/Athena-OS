"""add code_files prior_category prior_source

Revision ID: 74e855f74660
Revises: 84ed7134aa63
Create Date: 2026-08-06 20:31:58.934571

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '74e855f74660'
down_revision: Union[str, Sequence[str], None] = '84ed7134aa63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default required: code_files already has rows, both columns
    # are NOT NULL. Existing rows get the safe defaults ("source"/"graph"),
    # same as the model's Python-level defaults -- they'll be reclassified
    # for real on a full re-ingest (an incremental one won't touch unchanged
    # files' prior_category/prior_source, same caching behavior as kind).
    op.add_column('code_files', sa.Column('prior_category', sa.String(length=20), nullable=False, server_default='source'))
    op.add_column('code_files', sa.Column('prior_source', sa.String(length=20), nullable=False, server_default='graph'))


def downgrade() -> None:
    op.drop_column('code_files', 'prior_source')
    op.drop_column('code_files', 'prior_category')
