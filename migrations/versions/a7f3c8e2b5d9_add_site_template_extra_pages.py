"""add extra_pages to site_template

Revision ID: a7f3c8e2b5d9
Revises: 5b30c4eebff7
Create Date: 2026-11-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a7f3c8e2b5d9'
down_revision = '5b30c4eebff7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_template', schema=None) as batch_op:
        batch_op.add_column(sa.Column('extra_pages', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('site_template', schema=None) as batch_op:
        batch_op.drop_column('extra_pages')
