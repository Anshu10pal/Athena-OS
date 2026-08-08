"""phase I6 add hdbscan subsystem columns

Revision ID: 49b14fd05c27
Revises: 425611792c27
Create Date: 2026-08-08 22:11:59.253950

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '49b14fd05c27'
down_revision: Union[str, Sequence[str], None] = '425611792c27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Scoped to Phase I6's own change -- same pre-existing
    SQLite drift stripped out as every prior migration in this project."""
    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subsystem_hdbscan_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_code_files_subsystem_hdbscan_id'), ['subsystem_hdbscan_id'], unique=False)
        batch_op.create_foreign_key('fk_code_files_subsystem_hdbscan_id', 'code_subsystems', ['subsystem_hdbscan_id'], ['id'])

    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subsystem_hdbscan_agreement', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('subsystem_hdbscan_cycle_coherence', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('repos', schema=None) as batch_op:
        batch_op.drop_column('subsystem_hdbscan_cycle_coherence')
        batch_op.drop_column('subsystem_hdbscan_agreement')

    with op.batch_alter_table('code_files', schema=None) as batch_op:
        batch_op.drop_constraint('fk_code_files_subsystem_hdbscan_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_code_files_subsystem_hdbscan_id'))
        batch_op.drop_column('subsystem_hdbscan_id')
