"""add weekly digest schedule fields

Revision ID: c148cff50c10
Revises: 4139f16d553b
Create Date: 2026-10-28 00:00:00.000000

Stage 4's "Your week" digest -- weekly_weekday + last_weekly_run_date on
AlertDigestSchedule, alongside the existing daily send_hour/send_minute.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c148cff50c10'
down_revision = '4139f16d553b'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('alert_digest_schedule')}
    if 'weekly_weekday' not in cols:
        op.add_column('alert_digest_schedule', sa.Column('weekly_weekday', sa.Integer(), nullable=False, server_default='6'))
    if 'last_weekly_run_date' not in cols:
        op.add_column('alert_digest_schedule', sa.Column('last_weekly_run_date', sa.Date(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('alert_digest_schedule')}
    if 'last_weekly_run_date' in cols:
        op.drop_column('alert_digest_schedule', 'last_weekly_run_date')
    if 'weekly_weekday' in cols:
        op.drop_column('alert_digest_schedule', 'weekly_weekday')
