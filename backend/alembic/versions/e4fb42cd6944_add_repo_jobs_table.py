"""add repo_jobs table

Revision ID: e4fb42cd6944
Revises: 2efcd4008a96
Create Date: 2026-08-05 18:33:37.385790

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4fb42cd6944'
down_revision: Union[str, Sequence[str], None] = '2efcd4008a96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('repo_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('stage', sa.String(length=40), nullable=False),
        sa.Column('progress_current', sa.Integer(), nullable=False),
        sa.Column('progress_total', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_repo_jobs_repo_id', 'repo_jobs', ['repo_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_repo_jobs_repo_id', table_name='repo_jobs')
    op.drop_table('repo_jobs')
