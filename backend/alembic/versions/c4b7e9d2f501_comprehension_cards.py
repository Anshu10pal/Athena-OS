"""comprehension cards, with the card_source seam present from row one

Revision ID: c4b7e9d2f501
Revises: a1c9e37f4b82
Create Date: 2026-08-19

Phase 5's question bank. Separate from `module_assessments.questions` (a JSON
blob holding one user's attempt) because a card needs two things a blob cannot
give: a `card_source` COLUMN that grading dispatches on, and queryability --
"how many deterministic cards has this module", "which template produced this"
-- which a JSON list turns into a scan.

`card_source` is the seam, and it is a column rather than a convention
precisely so it cannot be a promise. It is written on every row from the first
one while only "deterministic" occurs, so adding the "llm" source later is
filling a declared hole rather than migrating existing rows into a
distinction they were never recorded with.

Cards carry no user state -- they are derived content, replaced wholesale when
a module regenerates. An ATTEMPT would carry user state and does not exist
yet; when it does it points HERE, and this table's rows must therefore be
stable enough to point at, which is why regeneration is per-module rather than
global.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4b7e9d2f501'
down_revision: Union[str, Sequence[str], None] = 'a1c9e37f4b82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'comprehension_cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('module_id', sa.Integer(), nullable=False),
        sa.Column('code_repo_id', sa.Integer(), nullable=True),
        sa.Column('card_source', sa.String(length=20), nullable=False,
                  server_default='deterministic'),
        sa.Column('template', sa.String(length=60), nullable=False, server_default=''),
        sa.Column('question', sa.Text(), nullable=False, server_default=''),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('answer', sa.Text(), nullable=False, server_default=''),
        sa.Column('rationale', sa.Text(), nullable=False, server_default=''),
        sa.Column('subject_path', sa.String(length=1000), nullable=True),
        sa.Column('code_commit_sha', sa.String(length=64), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_comprehension_cards_module_id'), 'comprehension_cards',
                    ['module_id'], unique=False)
    op.create_index(op.f('ix_comprehension_cards_code_repo_id'), 'comprehension_cards',
                    ['code_repo_id'], unique=False)
    # Indexed because the first questions asked of this table are "how many of
    # each source" and "give me the deterministic ones" -- the seam is not
    # decorative, it is a filter.
    op.create_index(op.f('ix_comprehension_cards_card_source'), 'comprehension_cards',
                    ['card_source'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_comprehension_cards_card_source'), table_name='comprehension_cards')
    op.drop_index(op.f('ix_comprehension_cards_code_repo_id'), table_name='comprehension_cards')
    op.drop_index(op.f('ix_comprehension_cards_module_id'), table_name='comprehension_cards')
    op.drop_table('comprehension_cards')
