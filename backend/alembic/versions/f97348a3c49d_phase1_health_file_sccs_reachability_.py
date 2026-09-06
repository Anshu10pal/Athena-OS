"""phase1 health file sccs reachability snapshots

Revision ID: f97348a3c49d
Revises: ccfd50ed1c72
Create Date: 2026-08-09 12:01:11.125880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'f97348a3c49d'
down_revision: Union[str, Sequence[str], None] = 'ccfd50ed1c72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Scoped to this phase's own change -- same pre-existing
    SQLite drift stripped out as every prior migration in this project."""
    op.create_table(
        'code_health_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('branch', sa.String(length=255), nullable=False),
        sa.Column('head_sha', sa.String(length=64), nullable=True),
        sa.Column('working_tree_dirty', sa.Boolean(), nullable=True),
        sa.Column('analyzer_version', sa.Integer(), nullable=False),
        sa.Column('thresholds_version', sa.Integer(), nullable=False),
        sa.Column('weights_version', sa.Integer(), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=False),
        sa.Column('axis_summary', sa.JSON(), nullable=False),
        sa.Column('files_scored', sa.Integer(), nullable=False),
        sa.Column('files_na', sa.Integer(), nullable=False),
        sa.Column('evidence_complete', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_code_health_snapshots_repo_id'), ['repo_id'], unique=False)

    op.create_table(
        'code_file_health',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(length=1000), nullable=False),
        sa.Column('nloc', sa.Integer(), nullable=False),
        sa.Column('maintainability', sa.Float(), nullable=True),
        sa.Column('architecture_health', sa.Float(), nullable=True),
        sa.Column('change_hotspot_points', sa.Float(), nullable=True),
        sa.Column('adjusted_exposure', sa.Float(), nullable=True),
        sa.Column('explanation', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['file_id'], ['code_files.id'], ),
        sa.ForeignKeyConstraint(['snapshot_id'], ['code_health_snapshots.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_id', 'file_id', name='uq_file_health_snapshot_file'),
    )
    with op.batch_alter_table('code_file_health', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_code_file_health_snapshot_id'), ['snapshot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_code_file_health_file_id'), ['file_id'], unique=False)

    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scc_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('scc_size', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reachable_from_entry', sa.Boolean(), nullable=True))
        batch_op.create_index(batch_op.f('ix_code_files_scc_id'), ['scc_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_code_files_scc_id'))
        batch_op.drop_column('reachable_from_entry')
        batch_op.drop_column('scc_size')
        batch_op.drop_column('scc_id')

    with op.batch_alter_table('code_file_health', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_code_file_health_file_id'))
        batch_op.drop_index(batch_op.f('ix_code_file_health_snapshot_id'))
    op.drop_table('code_file_health')

    with op.batch_alter_table('code_health_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_code_health_snapshots_repo_id'))
    op.drop_table('code_health_snapshots')
