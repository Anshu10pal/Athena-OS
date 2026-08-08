"""rename repos last_python_resolution_rate to high water mark

Revision ID: d2fb0eec7934
Revises: ad8e3430edc1
Create Date: 2026-08-07 11:20:19.929673

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2fb0eec7934'
down_revision: Union[str, Sequence[str], None] = 'ad8e3430edc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase F7 correction: the column tracked "last observed" resolution
    # rate, which let a second consecutive bad run re-baseline against an
    # already-collapsed value and pass. Renaming (not just re-documenting)
    # so the column's own name states what it actually holds now: the
    # highest rate ever recorded, never overwritten downward. A straight
    # rename preserves every existing value as-is -- the highest rate
    # recorded so far IS a valid high-water mark for that repo already.
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.alter_column('last_python_resolution_rate', new_column_name='python_resolution_high_water_mark')


def downgrade() -> None:
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.alter_column('python_resolution_high_water_mark', new_column_name='last_python_resolution_rate')
