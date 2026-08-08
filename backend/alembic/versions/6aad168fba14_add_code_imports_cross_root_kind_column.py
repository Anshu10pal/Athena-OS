"""add code_imports cross_root_kind column

Revision ID: 6aad168fba14
Revises: 0e01759764e2
Create Date: 2026-08-07 01:38:55.175882

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6aad168fba14'
down_revision: Union[str, Sequence[str], None] = '0e01759764e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no server_default needed: null means "not flagged", which
    # is correct for every existing row (cross_root flagging didn't exist
    # before this phase).
    with op.batch_alter_table('code_imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cross_root_kind', sa.String(length=30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('code_imports', schema=None) as batch_op:
        batch_op.drop_column('cross_root_kind')
