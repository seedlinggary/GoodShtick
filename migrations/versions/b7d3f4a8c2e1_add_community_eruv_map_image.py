"""add community eruv map image

Revision ID: b7d3f4a8c2e1
Revises: a9c4e1f2b3d7
Create Date: 2026-10-19 15:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7d3f4a8c2e1'
down_revision = 'a9c4e1f2b3d7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('community', sa.Column('eruv_map_image', sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column('community', 'eruv_map_image')
