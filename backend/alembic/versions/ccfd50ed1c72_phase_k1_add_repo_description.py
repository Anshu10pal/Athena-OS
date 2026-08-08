"""phase K1 add repo description

Revision ID: ccfd50ed1c72
Revises: 49b14fd05c27
Create Date: 2026-08-09 02:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ccfd50ed1c72'
down_revision: Union[str, Sequence[str], None] = '49b14fd05c27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Scoped to Phase K1's own change -- same pre-existing
    SQLite drift stripped out as every prior migration in this project."""
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('description_source', sa.String(length=30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('description_source')
        batch_op.drop_column('description')
