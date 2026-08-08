"""add repos table for codebase agent

Revision ID: c0a62258a8f6
Revises: c78a4d694ac5
Create Date: 2026-08-05 14:22:25.924245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c0a62258a8f6'
down_revision: Union[str, Sequence[str], None] = 'c78a4d694ac5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('repos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=False),
    sa.Column('owner', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=True),
    sa.Column('local_path', sa.String(length=1000), nullable=False),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('default_branch', sa.String(length=255), nullable=False),
    sa.Column('visibility', sa.String(length=20), nullable=False),
    sa.Column('source_root', sa.String(length=500), nullable=True),
    sa.Column('allow_external_llm', sa.Boolean(), nullable=False),
    sa.Column('last_ingested_sha', sa.String(length=64), nullable=True),
    sa.Column('last_ingested_at', sa.DateTime(), nullable=True),
    sa.Column('file_count', sa.Integer(), nullable=True),
    sa.Column('added_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('host', 'owner', 'name', name='uq_repo_host_owner_name')
    )
    # NOTE: autogenerate also detected the same pre-existing drift on interview_sessions,
    # node_content, roadmaps, and users noted in earlier migrations. Left out here too.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('repos')
