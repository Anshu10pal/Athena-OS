"""add content_roadmaps.aliases

Revision ID: 0870a557d922
Revises: a7842ddc4e40
Create Date: 2026-08-03 21:35:20.029278

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0870a557d922'
down_revision: Union[str, Sequence[str], None] = 'a7842ddc4e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default='[]' fills existing seeded rows -- table is already populated,
    # unlike modules.aliases which was added before any row existed.
    with op.batch_alter_table('content_roadmaps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('aliases', sa.JSON(), nullable=False, server_default='[]'))
    # NOTE: autogenerate also detected the same pre-existing drift on interview_sessions,
    # node_content, roadmaps, and users noted in earlier migrations. Left out here too.


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('content_roadmaps', schema=None) as batch_op:
        batch_op.drop_column('aliases')
