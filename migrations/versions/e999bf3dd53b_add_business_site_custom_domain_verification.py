"""add custom_domain_status/custom_domain_token to business_site

Revision ID: e999bf3dd53b
Revises: a5461ba9ed31
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e999bf3dd53b'
down_revision = 'a5461ba9ed31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('business_site', schema=None) as batch_op:
        batch_op.add_column(sa.Column('custom_domain_status', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('custom_domain_token', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('business_site', schema=None) as batch_op:
        batch_op.drop_column('custom_domain_token')
        batch_op.drop_column('custom_domain_status')
