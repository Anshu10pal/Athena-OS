"""add code_file_ranks table

Revision ID: 2efcd4008a96
Revises: 204acbf515f7
Create Date: 2026-08-05 17:49:13.978337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2efcd4008a96'
down_revision: Union[str, Sequence[str], None] = '204acbf515f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('code_file_ranks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('fan_in', sa.Integer(), nullable=False),
        sa.Column('fan_out', sa.Integer(), nullable=False),
        sa.Column('pagerank', sa.Float(), nullable=False),
        sa.Column('is_entry_point', sa.Boolean(), nullable=False),
        sa.Column('commit_count', sa.Integer(), nullable=True),
        sa.Column('distinct_authors', sa.Integer(), nullable=True),
        sa.Column('days_since_last_change', sa.Integer(), nullable=True),
        sa.Column('reduced_confidence', sa.Boolean(), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['file_id'], ['code_files.id'], ),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', name='uq_code_file_rank_file'),
    )
    op.create_index('ix_code_file_ranks_file_id', 'code_file_ranks', ['file_id'], unique=False)
    op.create_index('ix_code_file_ranks_repo_id', 'code_file_ranks', ['repo_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_code_file_ranks_repo_id', table_name='code_file_ranks')
    op.drop_index('ix_code_file_ranks_file_id', table_name='code_file_ranks')
    op.drop_table('code_file_ranks')
