"""add users.last_roadmap_id

Revision ID: 32ac6b9a0281
Revises: ee4dcb7feccb
Create Date: 2026-08-03 23:31:51.762954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '32ac6b9a0281'
down_revision: Union[str, Sequence[str], None] = 'ee4dcb7feccb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_roadmap_id', sa.Integer(), nullable=True))
    # NOTE: autogenerate also detected the same pre-existing drift on interview_sessions,
    # node_content, roadmaps, and users.voice noted in earlier migrations. Left out here too.


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('last_roadmap_id')
