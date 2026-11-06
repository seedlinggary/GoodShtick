"""add site_ai_usage table

Revision ID: c5e8a3f1b9d4
Revises: b3d6f9a2c7e1
Create Date: 2026-11-05 00:00:08.000000

Phase 12 of the business-owner website builder (see plan file
tender-inventing-teapot.md): the AI assistant's rate-limit counter.
Purely additive, schema only -- no ORM data seeding in this one (see
b3d6f9a2c7e1's own docstring for why that would be unsafe to mix with
DDL in the same migration transaction anyway).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5e8a3f1b9d4'
down_revision = 'b3d6f9a2c7e1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'site_ai_usage' not in existing_tables:
        op.create_table(
            'site_ai_usage',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('identity', sa.String(length=120), nullable=False),
            sa.Column('usage_date', sa.Date(), nullable=False),
            sa.Column('generate_count', sa.Integer(), nullable=False, server_default='0'),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('site_ai_usage')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('site_ai_usage')}
    with op.batch_alter_table('site_ai_usage', schema=None) as batch_op:
        if 'ix_site_ai_usage_identity' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_ai_usage_identity'), ['identity'], unique=False)
        if 'ix_site_ai_usage_usage_date' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_ai_usage_usage_date'), ['usage_date'], unique=False)
        if 'uq_site_ai_usage_identity_date' not in existing_uniques:
            batch_op.create_unique_constraint('uq_site_ai_usage_identity_date', ['identity', 'usage_date'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'site_ai_usage' in set(inspector.get_table_names()):
        op.drop_table('site_ai_usage')
