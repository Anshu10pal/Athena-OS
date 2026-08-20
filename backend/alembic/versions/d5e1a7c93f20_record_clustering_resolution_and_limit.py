"""record clustering resolution (gamma) and the resolution-limit diagnostic

Revision ID: d5e1a7c93f20
Revises: c8d3f1a24b67
Create Date: 2026-08-17

A cluster boundary is not a stable fact about the code -- eslint's
code-path-analysis subsystem resolved cleanly at 398 files and merged
entirely into a 119-member cluster at 1,447, same files and same edges
(docs/external-validation-eslint.md, Rounds 5 and 7). Nothing already
persisted recorded either the gamma a clustering ran at or how close each
cluster sat to the Fortunato-Barthelemy sqrt(2m) threshold, so two runs
could not be compared and a boundary could not be judged. These three
columns are what makes both possible after the fact.

All three are nullable with no backfill: rows written before this migration
genuinely ran at networkx's default gamma of 1.0, but writing that in would
be inventing provenance for runs that never recorded it. NULL means "not
recorded," which is the true statement.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5e1a7c93f20'
down_revision: Union[str, Sequence[str], None] = 'c8d3f1a24b67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('code_subsystems', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resolution', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('internal_weight', sa.Float(), nullable=True))

    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subsystem_resolution_limit', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('subsystem_resolution_limit')

    with op.batch_alter_table('code_subsystems', schema=None) as batch_op:
        batch_op.drop_column('internal_weight')
        batch_op.drop_column('resolution')
