"""phase1 health snapshot source fingerprint

Revision ID: e20bac3ed3b3
Revises: f97348a3c49d
Create Date: 2026-08-09 12:42:23.245066

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'e20bac3ed3b3'
down_revision: Union[str, Sequence[str], None] = 'f97348a3c49d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Scoped to this phase's own change -- same pre-existing
    SQLite drift stripped out as every prior migration in this project."""
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_fingerprint', sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_code_health_snapshots_source_fingerprint'),
            ['source_fingerprint'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_code_health_snapshots_source_fingerprint'))
        batch_op.drop_column('source_fingerprint')
