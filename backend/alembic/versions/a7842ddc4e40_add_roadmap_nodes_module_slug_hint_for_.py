"""add roadmap_nodes.module_slug hint for seed export round-trip

Revision ID: a7842ddc4e40
Revises: 2e631a0a0c04
Create Date: 2026-08-03 17:43:30.949455

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7842ddc4e40'
down_revision: Union[str, Sequence[str], None] = '2e631a0a0c04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('roadmap_nodes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('module_slug', sa.String(length=120), nullable=True))
    # NOTE: autogenerate also detected the same pre-existing drift on interview_sessions,
    # node_content, roadmaps, and users noted in the previous migration. Left out here too.


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('roadmap_nodes', schema=None) as batch_op:
        batch_op.drop_column('module_slug')
