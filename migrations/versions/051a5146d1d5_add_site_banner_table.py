"""add site banner table

Revision ID: 051a5146d1d5
Revises: 16d783158cda
Create Date: 2026-10-28 00:00:00.000000

Single-row settings table for the super-admin-editable site-wide
announcement banner shown on every one of GUT's 5 sites -- see
backend/banner/modals/banner.py.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '051a5146d1d5'
down_revision = '16d783158cda'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'site_banner' not in inspector.get_table_names():
        op.create_table(
            'site_banner',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('link_url', sa.String(length=500), nullable=True),
            sa.Column('link_text', sa.String(length=60), nullable=True),
            sa.Column('style', sa.String(length=20), nullable=False, server_default='info'),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'site_banner' in inspector.get_table_names():
        op.drop_table('site_banner')
