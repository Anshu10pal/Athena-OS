"""add repos.last_promoted_python_roots

Revision ID: ad8e3430edc1
Revises: e559d7c57580
Create Date: 2026-08-07 11:19:49.377256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad8e3430edc1'
down_revision: Union[str, Sequence[str], None] = 'e559d7c57580'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no server_default: null means "Python root promotion has
    # never run for this repo", distinct from "[]" (ran, promoted nothing)
    # -- correct for every existing row, since this tripwire didn't exist
    # before this phase.
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_promoted_python_roots', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('last_promoted_python_roots')
