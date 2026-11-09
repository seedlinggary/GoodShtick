"""add business_id to visitor_session

Revision ID: c3d9a1f6e274
Revises: a7f3c8e2b5d9
Create Date: 2026-11-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d9a1f6e274'
down_revision = 'a7f3c8e2b5d9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        batch_op.add_column(sa.Column('business_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_visitor_session_business_id'), ['business_id'], unique=False)


def downgrade():
    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_visitor_session_business_id'))
        batch_op.drop_column('business_id')
