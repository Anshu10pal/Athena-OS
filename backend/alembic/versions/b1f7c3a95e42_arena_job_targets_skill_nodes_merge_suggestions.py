"""interview arena phase A: job targets, skill nodes, merge suggestions

Revision ID: b1f7c3a95e42
Revises: d9f014c8a26b
Create Date: 2026-09-01

Phase A of the Interview Arena: a job description becomes a skill graph the
user confirms before any interview can start.

Namespaced `arena_*` rather than `interview_*`. The existing
`interview_sessions` table belongs to the original MVP interview flow, which is
still live and still read by analytics.py, achievements.py and activity.py --
so the name is taken, and taking it anyway would mean migrating user data into
a distinction it was never recorded with.

Three tables, not the full nine from the design. The remaining six (items,
exposures, sessions, responses, scores, ability estimates, reports) land in
their own phases, matching how the codebase-agent schema arrived. Only
`extractor_version` is declared ahead of its use, because it participates in
the idempotency key from row one.

Idempotency is (user_id, jd_hash, extractor_version), not jd_hash:
  - without user_id, user B pasting user A's JD receives A's hand-edited graph;
  - without extractor_version, the first graph built for a JD is served
    forever and a prompt improvement is invisible to every JD already stored.

Every column carries a server_default where the model has a Python default, so
a raw INSERT that names fewer columns still produces a valid row. Two
deliberate exceptions, both documented on the model: `arena_skill_nodes.
extraction_source` has NO default, because a default would make "the writer
forgot" indistinguishable from "the writer meant it" -- the same defect
ComprehensionCard.card_source records; and `graph_confirmed_at` is nullable
with no default because NULL is the meaningful state (unconfirmed), not a
missing value.

Types are Integer/String/Text/Float/Boolean/JSON/DateTime only -- the set
already running on both SQLite and Postgres in this schema. No JSONB, no ARRAY.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1f7c3a95e42'
down_revision: Union[str, Sequence[str], None] = 'd9f014c8a26b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'arena_job_targets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('jd_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('jd_hash', sa.String(length=64), nullable=False),
        sa.Column('extractor_version', sa.String(length=20), nullable=False),
        sa.Column('graph_confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('extraction_metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # The idempotency key. A UNIQUE CONSTRAINT rather than an application
        # check: two concurrent submissions of the same JD (a double-click on
        # the submit button is the realistic case) must not produce two graphs,
        # and only the database can promise that.
        sa.UniqueConstraint('user_id', 'jd_hash', 'extractor_version',
                            name='uq_arena_job_target_user_jd_extractor'),
    )
    op.create_index(op.f('ix_arena_job_targets_user_id'), 'arena_job_targets',
                    ['user_id'], unique=False)
    op.create_index(op.f('ix_arena_job_targets_jd_hash'), 'arena_job_targets',
                    ['jd_hash'], unique=False)

    op.create_table(
        'arena_skill_nodes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_target_id', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('canonical_name', sa.String(length=200), nullable=False),
        sa.Column('jd_weight', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('target_tier', sa.String(length=20), nullable=False,
                  server_default='working'),
        sa.Column('weight_signals_json', sa.JSON(), nullable=True),
        sa.Column('surface_forms_json', sa.JSON(), nullable=True),
        sa.Column('merge_evidence_json', sa.JSON(), nullable=True),
        sa.Column('source_spans_json', sa.JSON(), nullable=True),
        sa.Column('embedding_id', sa.String(length=64), nullable=True),
        # No server_default, on purpose. See the module docstring and the
        # model's own comment: a default here would let a fixture or a
        # half-written generator produce a row that CLAIMS an origin no code
        # path ever gave it, and `user_edited` correction signal would then be
        # attributed to the model rather than to the user.
        sa.Column('extraction_source', sa.String(length=20), nullable=False),
        sa.Column('user_edited', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_target_id'], ['arena_job_targets.id'], ),
        sa.ForeignKeyConstraint(['parent_id'], ['arena_skill_nodes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_arena_skill_nodes_job_target_id'), 'arena_skill_nodes',
                    ['job_target_id'], unique=False)
    # Indexed because the first query this table serves is "give me this
    # target's parents" (parent_id IS NULL) and then "give me this parent's
    # children" -- the graph is read by parentage on every render.
    op.create_index(op.f('ix_arena_skill_nodes_parent_id'), 'arena_skill_nodes',
                    ['parent_id'], unique=False)

    op.create_table(
        'arena_merge_suggestions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_target_id', sa.Integer(), nullable=False),
        # No ForeignKey on either node id, by design -- this row's purpose
        # includes outliving a node the user deleted. Same reasoning as
        # repo_deletion_audits.repo_id.
        sa.Column('left_node_id', sa.Integer(), nullable=False),
        sa.Column('right_node_id', sa.Integer(), nullable=False),
        sa.Column('left_name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('right_name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('enriched_cosine', sa.Float(), nullable=False, server_default='0'),
        sa.Column('bare_cosine', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_target_id'], ['arena_job_targets.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_arena_merge_suggestions_job_target_id'),
                    'arena_merge_suggestions', ['job_target_id'], unique=False)
    # Indexed because the questions asked of this table are "what is still
    # pending for this target" and, later, "give me every rejection" -- the
    # rejections being the labelled negative data the band retune needs. A
    # status filter that scans is a status filter nobody runs.
    op.create_index(op.f('ix_arena_merge_suggestions_status'),
                    'arena_merge_suggestions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_arena_merge_suggestions_status'),
                  table_name='arena_merge_suggestions')
    op.drop_index(op.f('ix_arena_merge_suggestions_job_target_id'),
                  table_name='arena_merge_suggestions')
    op.drop_table('arena_merge_suggestions')
    op.drop_index(op.f('ix_arena_skill_nodes_parent_id'),
                  table_name='arena_skill_nodes')
    op.drop_index(op.f('ix_arena_skill_nodes_job_target_id'),
                  table_name='arena_skill_nodes')
    op.drop_table('arena_skill_nodes')
    op.drop_index(op.f('ix_arena_job_targets_jd_hash'),
                  table_name='arena_job_targets')
    op.drop_index(op.f('ix_arena_job_targets_user_id'),
                  table_name='arena_job_targets')
    op.drop_table('arena_job_targets')
