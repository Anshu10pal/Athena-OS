"""add resource_history.topic_id

Revision ID: ee4dcb7feccb
Revises: 0870a557d922
Create Date: 2026-08-03 23:16:39.205604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ee4dcb7feccb'
down_revision: Union[str, Sequence[str], None] = '0870a557d922'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Table is empty (no resource-editing endpoints existed before this phase),
    # so no server_default is needed for the NOT NULL column.
    with op.batch_alter_table('resource_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('topic_id', sa.Integer(), nullable=False))
        batch_op.create_index(batch_op.f('ix_resource_history_topic_id'), ['topic_id'], unique=False)
    # NOTE: autogenerate also detected the same pre-existing drift on interview_sessions,
    # node_content, roadmaps, and users noted in earlier migrations. Left out here too.


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('resource_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_resource_history_topic_id'))
        batch_op.drop_column('topic_id')
