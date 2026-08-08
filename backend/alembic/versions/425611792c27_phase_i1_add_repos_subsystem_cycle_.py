"""phase I1 add repos subsystem_cycle_coherence

Revision ID: 425611792c27
Revises: 8dc08ed8f03e
Create Date: 2026-08-08 15:52:10.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '425611792c27'
down_revision: Union[str, Sequence[str], None] = '8dc08ed8f03e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Scoped to Phase I1's own change -- same pre-existing
    SQLite drift stripped out as every prior migration in this project."""
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subsystem_cycle_coherence', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('subsystem_cycle_coherence')
