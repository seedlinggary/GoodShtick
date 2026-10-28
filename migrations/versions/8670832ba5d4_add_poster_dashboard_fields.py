"""add poster dashboard fields

Revision ID: 8670832ba5d4
Revises: c148cff50c10
Create Date: 2026-10-28 00:00:00.000000

Stage 5's poster dashboard + "Still available?" check groundwork:
- estates_listing: contact_taps, status, still_available_confirmed_at,
  still_available_reminder_sent_at
- tachlis_post: views_count, contact_taps, status, renewed_count,
  still_available_confirmed_at, still_available_reminder_sent_at
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8670832ba5d4'
down_revision = 'c148cff50c10'
branch_labels = None
depends_on = None

ESTATES_NEW = ['contact_taps', 'status', 'still_available_confirmed_at', 'still_available_reminder_sent_at']
TACHLIS_NEW = [
    'views_count', 'contact_taps', 'status', 'renewed_count',
    'still_available_confirmed_at', 'still_available_reminder_sent_at',
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    estates_cols = {c['name'] for c in inspector.get_columns('estates_listing')}
    if 'contact_taps' not in estates_cols:
        op.add_column('estates_listing', sa.Column('contact_taps', sa.Integer(), nullable=False, server_default='0'))
    if 'status' not in estates_cols:
        op.add_column('estates_listing', sa.Column('status', sa.String(length=20), nullable=False, server_default='active'))
    if 'still_available_confirmed_at' not in estates_cols:
        op.add_column('estates_listing', sa.Column('still_available_confirmed_at', sa.DateTime(), nullable=True))
    if 'still_available_reminder_sent_at' not in estates_cols:
        op.add_column('estates_listing', sa.Column('still_available_reminder_sent_at', sa.DateTime(), nullable=True))

    tachlis_cols = {c['name'] for c in inspector.get_columns('tachlis_post')}
    if 'views_count' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('views_count', sa.Integer(), nullable=False, server_default='0'))
    if 'contact_taps' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('contact_taps', sa.Integer(), nullable=False, server_default='0'))
    if 'status' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('status', sa.String(length=20), nullable=False, server_default='active'))
    if 'renewed_count' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('renewed_count', sa.Integer(), nullable=False, server_default='0'))
    if 'still_available_confirmed_at' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('still_available_confirmed_at', sa.DateTime(), nullable=True))
    if 'still_available_reminder_sent_at' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('still_available_reminder_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    estates_cols = {c['name'] for c in inspector.get_columns('estates_listing')}
    for col in ESTATES_NEW:
        if col in estates_cols:
            op.drop_column('estates_listing', col)

    tachlis_cols = {c['name'] for c in inspector.get_columns('tachlis_post')}
    for col in TACHLIS_NEW:
        if col in tachlis_cols:
            op.drop_column('tachlis_post', col)
