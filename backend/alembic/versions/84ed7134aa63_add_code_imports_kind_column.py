"""add code_imports kind column

Revision ID: 84ed7134aa63
Revises: e4fb42cd6944
Create Date: 2026-08-06 20:16:02.013605

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '84ed7134aa63'
down_revision: Union[str, Sequence[str], None] = 'e4fb42cd6944'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default required: code_imports already has rows (this repo's
    # own dev DB has 1216), and this column is NOT NULL. Existing rows get
    # 'light_use' as a placeholder -- unlike import RESOLUTION (which reruns
    # for every row on every ingest), classification only happens when a
    # file is actually (re)parsed, and unchanged files skip parsing
    # entirely. A normal incremental re-ingest will NOT reclassify existing
    # rows; a full re-ingest (fresh parse of every file) is needed to get
    # real kind values for data ingested before this migration.
    op.add_column('code_imports', sa.Column('kind', sa.String(length=30), nullable=False, server_default='light_use'))


def downgrade() -> None:
    op.drop_column('code_imports', 'kind')
