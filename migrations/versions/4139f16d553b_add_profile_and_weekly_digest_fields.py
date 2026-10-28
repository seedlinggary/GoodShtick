"""add profile and weekly digest fields to user

Revision ID: 4139f16d553b
Revises: 73795ce65d85
Create Date: 2026-10-28 00:00:00.000000

Stage 4's "one profile, one personal feed" (profile_area/budget_min/
budget_max/family_size/line_of_work, all optional) and "Your week" digest
(weekly_digest_enabled/weekly_digest_token/last_weekly_digest_at). See
backend/user/modals/user.py.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4139f16d553b'
down_revision = '73795ce65d85'
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    'profile_area', 'budget_min', 'budget_max', 'family_size', 'line_of_work',
    'weekly_digest_enabled', 'weekly_digest_token', 'last_weekly_digest_at',
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('user')}

    if 'profile_area' not in cols:
        op.add_column('user', sa.Column('profile_area', sa.String(length=100), nullable=True))
    if 'budget_min' not in cols:
        op.add_column('user', sa.Column('budget_min', sa.Integer(), nullable=True))
    if 'budget_max' not in cols:
        op.add_column('user', sa.Column('budget_max', sa.Integer(), nullable=True))
    if 'family_size' not in cols:
        op.add_column('user', sa.Column('family_size', sa.Integer(), nullable=True))
    if 'line_of_work' not in cols:
        op.add_column('user', sa.Column('line_of_work', sa.String(length=30), nullable=True))
    if 'weekly_digest_enabled' not in cols:
        op.add_column('user', sa.Column('weekly_digest_enabled', sa.Boolean(), nullable=False, server_default='true'))
    if 'weekly_digest_token' not in cols:
        op.add_column('user', sa.Column('weekly_digest_token', sa.String(length=64), nullable=True))
        op.create_unique_constraint('uq_user_weekly_digest_token', 'user', ['weekly_digest_token'])
    if 'last_weekly_digest_at' not in cols:
        op.add_column('user', sa.Column('last_weekly_digest_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('user')}
    if 'weekly_digest_token' in cols:
        op.drop_constraint('uq_user_weekly_digest_token', 'user', type_='unique')
    for col in NEW_COLUMNS:
        if col in cols:
            op.drop_column('user', col)
