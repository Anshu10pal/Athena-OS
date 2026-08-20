"""codebase roadmap persistence: repo provenance on modules and roadmaps

Revision ID: f8a3c21d9b45
Revises: e6f2b8d41a37
Create Date: 2026-08-17

Phase 4 writes derived rows into modules/topics/resources/content_roadmaps --
tables that already hold hand-written seed content and LLM-generated content.
"Replace this repo's derived rows" has to be expressible as a QUERY for that
to be safe, and until now it was not: `modules` had `source` but no repo, so
the only way to identify a repo's modules was to parse the repo id back out of
the slug that embeds it, making a naming convention load-bearing for a DELETE.

`code_repo_id` on both tables makes the scope explicit. NULL on every existing
row, which is correct -- seed and generated content has no repo.

Neither column carries a ForeignKey, matching the existing
`resources.code_repo_id` groundwork (b7c2e4d9a015) and for the same reason: a
repo can be deleted while the content derived from it is deliberately kept, and
a FK would either block that or cascade away the content.

`staging_basis` records whether a roadmap's stages are BFS layers from entry
points or module dependency depth. Stored rather than inferred from stage
titles, because the same roadmap page renders both and the two mean different
things.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f8a3c21d9b45'
down_revision: Union[str, Sequence[str], None] = 'e6f2b8d41a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('code_repo_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_modules_code_repo_id'), ['code_repo_id'], unique=False)

    with op.batch_alter_table('content_roadmaps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('code_repo_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('staging_basis', sa.String(length=20), nullable=True))
        batch_op.create_index(batch_op.f('ix_content_roadmaps_code_repo_id'), ['code_repo_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('content_roadmaps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_content_roadmaps_code_repo_id'))
        batch_op.drop_column('staging_basis')
        batch_op.drop_column('code_repo_id')

    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_modules_code_repo_id'))
        batch_op.drop_column('code_repo_id')
