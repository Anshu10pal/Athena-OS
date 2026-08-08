"""phase H1.5 persist seed_eligible on code_files

Revision ID: 2d10dc1df104
Revises: 6a601d21fa80
Create Date: 2026-08-07 23:42:14.676316

GET /repos/{id}/graph's directory-level view (Phase H1) needed the
seed-eligible/prior-only entry split for its entry-vs-tooling kind, and
was getting it by calling entry_detection live, on every read -- the
same duplicated-computation shape Phase G1 already fixed once for
fan_in/fan_out/commit history, except this instance also measurably
cost 15-20s per request (entry detection walks the repo's filesystem).
No backfill: unlike G1's migration, there is no prior column anywhere
this value already lived -- it's genuinely new, populated by the next
rank run for any repo, same as a freshly-added history column is null
until a repo's first rank run after upgrading.

Autogenerate also proposed a pile of unrelated NOT NULL/index changes
across other tables (pre-existing drift from other models, not
anything this phase touched) and dropping a leftover SQLite batch-mode
temp table -- none of that belongs in this migration, so only the one
real column addition is kept below.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2d10dc1df104'
down_revision: Union[str, Sequence[str], None] = '6a601d21fa80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seed_eligible', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.drop_column('seed_eligible')
