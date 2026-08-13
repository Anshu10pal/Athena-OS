"""add files_partially_na to health snapshots

Revision ID: a4f1c9e07b52
Revises: 263062fc7f7f
Create Date: 2026-08-13 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f1c9e07b52'
down_revision: Union[str, Sequence[str], None] = '263062fc7f7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `files_partially_na` beside `files_na`.

    `files_na` counts files N/A on EVERY axis. That is a defensible definition
    and a misleading number alone: on apache/superset it reads 0 while 782 files
    (12.0%) are scored on architecture only, their maintainability and
    change_hotspot axes excluded for being under ten lines. Surfaced in a UI,
    "files_na: 0" says every file was scored when an eighth of them were not
    scored on two thirds of the model.

    NULLABLE, and not backfilled. Two decisions, both load-bearing:

    Not recomputed, because the count belongs to the snapshot that produced it
    and deriving it now would apply today's definition to historical rows --
    the same error class as reading a finding count computed under one
    instrument as if computed under another.

    NULL rather than 0, because those two say different things. 0 means "this
    snapshot measured it and found none"; NULL means "this snapshot never
    measured it". Backfilling 0 would make every historical snapshot claim it
    had no partially-scored files, which for apache/superset would be a
    confident wrong answer about 782 of them. That is exclude-don't-zero
    applied to a schema.

    Note the previous migration's lesson applies here too -- tests build their
    schema from the models via create_all, so a model/migration divergence is
    invisible to them and this file is the only thing that fixes a live
    database.
    """
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('files_partially_na', sa.Integer(),
                                      nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.drop_column('files_partially_na')
