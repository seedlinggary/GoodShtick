"""add payment_account table

Revision ID: c9e4a2d7f3b6
Revises: b7d3f1a6c8e2
Create Date: 2026-11-05 00:00:02.000000

Phase 3 of the business-owner website builder (see plan file
tender-inventing-teapot.md): one row per business's connected payment
processor (Stripe Connect today). Purely additive -- no existing table or
column is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9e4a2d7f3b6'
down_revision = 'b7d3f1a6c8e2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'payment_account' not in existing_tables:
        op.create_table(
            'payment_account',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('provider', sa.String(length=32), nullable=False, server_default='stripe'),
            sa.Column('external_account_id', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('details', sa.JSON(), nullable=True),
            sa.Column('connected_by', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('connected_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('payment_account')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('payment_account')}

    with op.batch_alter_table('payment_account', schema=None) as batch_op:
        if 'ix_payment_account_business_id' not in existing_indexes and 'uq_payment_account_business_id' not in existing_uniques:
            batch_op.create_index(batch_op.f('ix_payment_account_business_id'), ['business_id'], unique=True)
        if 'ix_payment_account_provider' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_payment_account_provider'), ['provider'], unique=False)
        if 'ix_payment_account_status' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_payment_account_status'), ['status'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'payment_account' in set(inspector.get_table_names()):
        op.drop_table('payment_account')
