"""record per-cluster stability under a resolution perturbation

Revision ID: e6f2b8d41a37
Revises: d5e1a7c93f20
Create Date: 2026-08-17

d5e1a7c93f20 added `internal_weight` so a cluster could be compared against
the repo-wide sqrt(2m) threshold. Measuring that against reality showed the
threshold is a poor predictor of whether a boundary actually moves -- it
over-flags on large graphs (Superset: 97% below threshold, 6% actually
dissolved) and under-flags on small ones (Athena-OS: 33% below, 67%
dissolved). sqrt(2m) says what modularity COULD fail to resolve; this column
records what it DID, by re-clustering the same graph at a higher gamma and
asking whether each cluster's members land together again.

Nullable with no backfill, and NULL means NOT MEASURED -- the check is
config-gated, and hdbscan has no resolution parameter to perturb. Reading
NULL as "stable" would invert the column's meaning on exactly the rows that
were never tested.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6f2b8d41a37'
down_revision: Union[str, Sequence[str], None] = 'd5e1a7c93f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('code_subsystems', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stable_under_perturbation', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('code_subsystems', schema=None) as batch_op:
        batch_op.drop_column('stable_under_perturbation')
