"""add alert table

Revision ID: 808babf27e60
Revises: f3a7c1e9b542
Create Date: 2026-10-28 00:00:00.000000

Stage 3 of gut_next_level_agent.md ("Get alerts for this search"). One
saved-search row per alert, confirmed by email before anything is ever
sent, with its own unsubscribe token. See backend/alerts/modals/alert.py
for the full field-by-field rationale.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '808babf27e60'
down_revision = 'f3a7c1e9b542'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'alert' in inspector.get_table_names():
        return

    op.create_table(
        'alert',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=True),
        sa.Column('search_type', sa.String(length=20), nullable=False),
        sa.Column('filters', sa.Text(), nullable=False),
        sa.Column('label', sa.String(length=300), nullable=True),
        sa.Column('confirmed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('confirm_token', sa.String(length=64), nullable=False),
        sa.Column('unsubscribe_token', sa.String(length=64), nullable=False),
        sa.Column('paused', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_notified_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.public_id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('confirm_token'),
        sa.UniqueConstraint('unsubscribe_token'),
    )
    with op.batch_alter_table('alert', schema=None) as batch_op:
        batch_op.create_index('ix_alert_email', ['email'])
        batch_op.create_index('ix_alert_user_id', ['user_id'])
        batch_op.create_index('ix_alert_search_type', ['search_type'])
        batch_op.create_index('ix_alert_confirm_token', ['confirm_token'])
        batch_op.create_index('ix_alert_unsubscribe_token', ['unsubscribe_token'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'alert' in inspector.get_table_names():
        op.drop_table('alert')
