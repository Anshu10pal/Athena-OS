"""add content_roadmaps.category

Revision ID: c78a4d694ac5
Revises: 32ac6b9a0281
Create Date: 2026-08-04 00:53:13.646624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c78a4d694ac5'
down_revision: Union[str, Sequence[str], None] = '32ac6b9a0281'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default='role' fills the already-seeded rows -- table is populated.
    with op.batch_alter_table('content_roadmaps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=20), nullable=False, server_default='role'))
    # NOTE: autogenerate also detected the same pre-existing drift on interview_sessions,
    # node_content, roadmaps, and users noted in earlier migrations. Left out here too.


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('content_roadmaps', schema=None) as batch_op:
        batch_op.drop_column('category')
