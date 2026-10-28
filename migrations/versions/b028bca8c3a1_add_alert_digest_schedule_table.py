"""add alert_digest_schedule table

Revision ID: b028bca8c3a1
Revises: 808babf27e60
Create Date: 2026-10-28 00:00:00.000000

Single-row table holding the Israel-local hour/minute the daily alert
digest should send, editable by a super admin with no redeploy. See
backend/alerts/modals/alert.py's AlertDigestSchedule and
routes/alert.py's _maybe_run_scheduled_digest().
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b028bca8c3a1'
down_revision = '808babf27e60'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'alert_digest_schedule' in inspector.get_table_names():
        return

    op.create_table(
        'alert_digest_schedule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('send_hour', sa.Integer(), nullable=False, server_default='9'),
        sa.Column('send_minute', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_run_date', sa.Date(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'alert_digest_schedule' in inspector.get_table_names():
        op.drop_table('alert_digest_schedule')
