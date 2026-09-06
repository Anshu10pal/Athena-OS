"""rename health snapshot evidence_complete to inputs_complete

Revision ID: 263062fc7f7f
Revises: e20bac3ed3b3
Create Date: 2026-08-09 12:51:19.977852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '263062fc7f7f'
down_revision: Union[str, Sequence[str], None] = 'e20bac3ed3b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename `evidence_complete` -> `inputs_complete`.

    The field asserts only that every marker IN THIS CONTRACT had its input,
    not that the evidence about the architecture is complete -- the old name
    overclaimed, and it propagates into API payloads and the UI.

    Caught by a live 500, not by the test suite: tests build their schema from
    the models via create_all, so a model/migration divergence is invisible to
    them. Worth remembering when renaming any persisted column here.
    """
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.alter_column('evidence_complete', new_column_name='inputs_complete',
                              existing_type=sa.Boolean(), existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.alter_column('inputs_complete', new_column_name='evidence_complete',
                              existing_type=sa.Boolean(), existing_nullable=False)
