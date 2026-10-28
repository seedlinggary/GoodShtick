"""add still available check fields

Revision ID: 16d783158cda
Revises: f2830a86b18c
Create Date: 2026-10-28 00:00:00.000000

Stage 5's "Still available?" check -- still_available_token on both
estates_listing and tachlis_post (the confirm-link token; the
still_available_confirmed_at/reminder_sent_at columns these pair with
already exist from an earlier migration), plus the global
still_available_check_enabled on/off switch on alert_digest_schedule,
which defaults OFF -- see backend/alerts/modals/alert.py's own comment on
why this one stays off until a super admin explicitly turns it on.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16d783158cda'
down_revision = 'f2830a86b18c'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    estates_cols = {c['name'] for c in inspector.get_columns('estates_listing')}
    if 'still_available_token' not in estates_cols:
        op.add_column('estates_listing', sa.Column('still_available_token', sa.String(length=64), nullable=True))
        op.create_unique_constraint('uq_estates_listing_still_available_token', 'estates_listing', ['still_available_token'])

    tachlis_cols = {c['name'] for c in inspector.get_columns('tachlis_post')}
    if 'still_available_token' not in tachlis_cols:
        op.add_column('tachlis_post', sa.Column('still_available_token', sa.String(length=64), nullable=True))
        op.create_unique_constraint('uq_tachlis_post_still_available_token', 'tachlis_post', ['still_available_token'])

    schedule_cols = {c['name'] for c in inspector.get_columns('alert_digest_schedule')}
    if 'still_available_check_enabled' not in schedule_cols:
        op.add_column('alert_digest_schedule', sa.Column('still_available_check_enabled', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    estates_cols = {c['name'] for c in inspector.get_columns('estates_listing')}
    if 'still_available_token' in estates_cols:
        op.drop_constraint('uq_estates_listing_still_available_token', 'estates_listing', type_='unique')
        op.drop_column('estates_listing', 'still_available_token')

    tachlis_cols = {c['name'] for c in inspector.get_columns('tachlis_post')}
    if 'still_available_token' in tachlis_cols:
        op.drop_constraint('uq_tachlis_post_still_available_token', 'tachlis_post', type_='unique')
        op.drop_column('tachlis_post', 'still_available_token')

    schedule_cols = {c['name'] for c in inspector.get_columns('alert_digest_schedule')}
    if 'still_available_check_enabled' in schedule_cols:
        op.drop_column('alert_digest_schedule', 'still_available_check_enabled')
