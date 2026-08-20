"""durable record of repo deletions

Revision ID: d9f014c8a26b
Revises: c4b7e9d2f501
Create Date: 2026-08-19

Diagnostic infrastructure, deliberately its own migration and its own change --
it is not part of any feature.

History this closes: a repo vanished from all eight tables with no explanation,
because `delete_repo` had no logging at all. Logging was added. It then fired
for exactly one real deletion (repo 8) and wrote to a process stdout nobody
captured -- so the question it existed to answer, "was delete_repo called and
on what", was still unanswerable afterwards.

The lesson the second incident taught, which the first did not: "the code path
fires" and "the output can be read back" are different claims, and only the
second is worth anything at the moment somebody notices a repo is missing --
which is always after the process that removed it has exited.

No ForeignKey to `repos`: the row's whole purpose is to outlive that row. And
`delete_repo` never deletes from this table -- an audit trail that a delete can
erase is not one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd9f014c8a26b'
down_revision: Union[str, Sequence[str], None] = 'c4b7e9d2f501'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'repo_deletion_audits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('repo_label', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('source_kind', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('rows_deleted', sa.JSON(), nullable=True),
        sa.Column('rows_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('directory_path', sa.String(length=1000), nullable=True),
        sa.Column('directory_deleted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_repo_deletion_audits_repo_id'), 'repo_deletion_audits',
                    ['repo_id'], unique=False)
    op.create_index(op.f('ix_repo_deletion_audits_created_at'), 'repo_deletion_audits',
                    ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_repo_deletion_audits_created_at'), table_name='repo_deletion_audits')
    op.drop_index(op.f('ix_repo_deletion_audits_repo_id'), table_name='repo_deletion_audits')
    op.drop_table('repo_deletion_audits')
