"""add askgut_usage table

Revision ID: a9c485337e48
Revises: 28d750af3f47
Create Date: 2026-10-29 00:00:00.000002

Per-caller, per-day message counter backing Ask GUT's daily rate cap (see
backend/askgut/modals/usage.py, backend/askgut/routes/chat.py) -- the
cost/abuse guardrail nothing else calling the OpenAI API in this codebase
has needed before, since every other GPT call site is an admin-triggered
batch job, not a public-facing endpoint. Brand-new table, nothing existing
is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table/indexes already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c485337e48'
down_revision = '28d750af3f47'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'askgut_usage' not in inspector.get_table_names():
        op.create_table(
            'askgut_usage',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('identity', sa.String(length=120), nullable=False),
            sa.Column('usage_date', sa.Date(), nullable=False),
            sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('identity', 'usage_date', name='uq_askgut_usage_identity_date'),
        )

    existing_indexes = set()
    if 'askgut_usage' in inspector.get_table_names():
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('askgut_usage')}

    with op.batch_alter_table('askgut_usage', schema=None) as batch_op:
        if 'ix_askgut_usage_identity' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_askgut_usage_identity'), ['identity'], unique=False)
        if 'ix_askgut_usage_usage_date' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_askgut_usage_usage_date'), ['usage_date'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'askgut_usage' in inspector.get_table_names():
        op.drop_table('askgut_usage')
