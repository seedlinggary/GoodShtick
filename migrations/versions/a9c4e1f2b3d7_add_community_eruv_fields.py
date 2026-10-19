"""add community eruv fields

Revision ID: a9c4e1f2b3d7
Revises: f3a7c2b891de
Create Date: 2026-10-19 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9c4e1f2b3d7'
down_revision = 'f3a7c2b891de'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('community', sa.Column('eruv_status', sa.String(length=300), nullable=True))
    op.add_column('community', sa.Column('eruv_url', sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column('community', 'eruv_url')
    op.drop_column('community', 'eruv_status')
