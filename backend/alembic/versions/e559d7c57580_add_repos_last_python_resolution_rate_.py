"""add repos last_python_resolution_rate column

Revision ID: e559d7c57580
Revises: 6aad168fba14
Create Date: 2026-08-07 10:45:27.124649

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e559d7c57580'
down_revision: Union[str, Sequence[str], None] = '6aad168fba14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no server_default: null means "no rank has run for this
    # repo yet", correct for every existing row (this tripwire didn't
    # exist before this phase).
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_python_resolution_rate', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('last_python_resolution_rate')
