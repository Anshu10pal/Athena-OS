"""add code_files code_symbols code_imports tables

Revision ID: 204acbf515f7
Revises: c0a62258a8f6
Create Date: 2026-08-05 17:01:22.217009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '204acbf515f7'
down_revision: Union[str, Sequence[str], None] = 'c0a62258a8f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('code_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(length=1000), nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('line_count', sa.Integer(), nullable=False),
        sa.Column('last_parsed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repo_id', 'path', name='uq_code_file_repo_path'),
    )
    op.create_index('ix_code_files_content_sha256', 'code_files', ['content_sha256'], unique=False)
    op.create_index('ix_code_files_repo_id', 'code_files', ['repo_id'], unique=False)

    op.create_table('code_symbols',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('parent_symbol_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('signature', sa.Text(), nullable=False),
        sa.Column('docstring', sa.Text(), nullable=True),
        sa.Column('line_start', sa.Integer(), nullable=False),
        sa.Column('line_end', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['file_id'], ['code_files.id'], ),
        sa.ForeignKeyConstraint(['parent_symbol_id'], ['code_symbols.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_code_symbols_file_id', 'code_symbols', ['file_id'], unique=False)
    op.create_index('ix_code_symbols_parent_symbol_id', 'code_symbols', ['parent_symbol_id'], unique=False)

    op.create_table('code_imports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('from_file_id', sa.Integer(), nullable=False),
        sa.Column('raw_specifier', sa.String(length=1000), nullable=False),
        sa.Column('imported_names', sa.JSON(), nullable=False),
        sa.Column('to_file_id', sa.Integer(), nullable=True),
        sa.Column('to_symbol_id', sa.Integer(), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['from_file_id'], ['code_files.id'], ),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.ForeignKeyConstraint(['to_file_id'], ['code_files.id'], ),
        sa.ForeignKeyConstraint(['to_symbol_id'], ['code_symbols.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_code_imports_from_file_id', 'code_imports', ['from_file_id'], unique=False)
    op.create_index('ix_code_imports_repo_id', 'code_imports', ['repo_id'], unique=False)
    op.create_index('ix_code_imports_to_file_id', 'code_imports', ['to_file_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_code_imports_to_file_id', table_name='code_imports')
    op.drop_index('ix_code_imports_repo_id', table_name='code_imports')
    op.drop_index('ix_code_imports_from_file_id', table_name='code_imports')
    op.drop_table('code_imports')

    op.drop_index('ix_code_symbols_parent_symbol_id', table_name='code_symbols')
    op.drop_index('ix_code_symbols_file_id', table_name='code_symbols')
    op.drop_table('code_symbols')

    op.drop_index('ix_code_files_repo_id', table_name='code_files')
    op.drop_index('ix_code_files_content_sha256', table_name='code_files')
    op.drop_table('code_files')
