"""add visitor_ip_throttle table (analytics bot protection)

Revision ID: 5b30c4eebff7
Revises: e999bf3dd53b
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '5b30c4eebff7'
down_revision = 'e999bf3dd53b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'visitor_ip_throttle',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('identity', sa.String(length=64), nullable=False),
        sa.Column('usage_date', sa.Date(), nullable=False),
        sa.Column('count', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('identity', 'usage_date', name='uq_visitor_ip_throttle_identity_date'),
    )
    with op.batch_alter_table('visitor_ip_throttle', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_visitor_ip_throttle_identity'), ['identity'], unique=False)
        batch_op.create_index(batch_op.f('ix_visitor_ip_throttle_usage_date'), ['usage_date'], unique=False)


def downgrade():
    with op.batch_alter_table('visitor_ip_throttle', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_visitor_ip_throttle_usage_date'))
        batch_op.drop_index(batch_op.f('ix_visitor_ip_throttle_identity'))
    op.drop_table('visitor_ip_throttle')
