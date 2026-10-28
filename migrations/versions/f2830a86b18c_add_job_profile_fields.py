"""add job profile fields to user

Revision ID: f2830a86b18c
Revises: 8670832ba5d4
Create Date: 2026-10-28 00:00:00.000000

Stage 5's "Job profile and one-tap apply" -- cv_summary, cv_contact,
open_to_work on the user table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2830a86b18c'
down_revision = '8670832ba5d4'
branch_labels = None
depends_on = None

NEW_COLUMNS = ['cv_summary', 'cv_contact', 'open_to_work']


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('user')}

    if 'cv_summary' not in cols:
        op.add_column('user', sa.Column('cv_summary', sa.Text(), nullable=True))
    if 'cv_contact' not in cols:
        op.add_column('user', sa.Column('cv_contact', sa.String(length=300), nullable=True))
    if 'open_to_work' not in cols:
        op.add_column('user', sa.Column('open_to_work', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('user')}
    for col in NEW_COLUMNS:
        if col in cols:
            op.drop_column('user', col)
