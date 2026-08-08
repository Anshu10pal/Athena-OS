"""phase I1 add code_subsystems table

Revision ID: 8dc08ed8f03e
Revises: 2d10dc1df104
Create Date: 2026-08-08 15:28:23.403204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8dc08ed8f03e'
down_revision: Union[str, Sequence[str], None] = '2d10dc1df104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Scoped to Phase I1's own change only -- the
    autogenerate run also picked up the same pre-existing SQLite drift
    (interview_sessions/node_content/roadmaps/users NOT NULL fixes,
    the stale _alembic_tmp_interview_sessions leftover) every prior
    migration in this project has stripped back out before applying."""
    op.create_table(
        'code_subsystems',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('algorithm', sa.String(length=20), nullable=False),
        sa.Column('cluster_index', sa.Integer(), nullable=False),
        sa.Column('member_count', sa.Integer(), nullable=False),
        sa.Column('dominant_prefix_label', sa.String(length=500), nullable=False),
        sa.Column('dominant_prefix_count', sa.Integer(), nullable=False),
        sa.Column('top_fan_in_label', sa.String(length=255), nullable=False),
        sa.Column('top_fan_in_file_id', sa.Integer(), nullable=True),
        sa.Column('custom_label', sa.String(length=255), nullable=True),
        sa.Column('active_label_rule', sa.String(length=20), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.ForeignKeyConstraint(['top_fan_in_file_id'], ['code_files.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repo_id', 'algorithm', 'cluster_index', name='uq_code_subsystem_repo_algo_index'),
    )
    with op.batch_alter_table('code_subsystems', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_code_subsystems_repo_id'), ['repo_id'], unique=False)

    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subsystem_modularity_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('subsystem_louvain_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_code_files_subsystem_modularity_id'), ['subsystem_modularity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_code_files_subsystem_louvain_id'), ['subsystem_louvain_id'], unique=False)
        batch_op.create_foreign_key('fk_code_files_subsystem_modularity_id', 'code_subsystems', ['subsystem_modularity_id'], ['id'])
        batch_op.create_foreign_key('fk_code_files_subsystem_louvain_id', 'code_subsystems', ['subsystem_louvain_id'], ['id'])

    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subsystem_algorithm_agreement', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('subsystem_algorithm_agreement')

    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.drop_constraint('fk_code_files_subsystem_modularity_id', type_='foreignkey')
        batch_op.drop_constraint('fk_code_files_subsystem_louvain_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_code_files_subsystem_louvain_id'))
        batch_op.drop_index(batch_op.f('ix_code_files_subsystem_modularity_id'))
        batch_op.drop_column('subsystem_louvain_id')
        batch_op.drop_column('subsystem_modularity_id')

    with op.batch_alter_table('code_subsystems', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_code_subsystems_repo_id'))

    op.drop_table('code_subsystems')
