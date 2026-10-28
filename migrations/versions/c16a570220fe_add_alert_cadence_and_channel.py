"""add alert cadence and channel

Revision ID: c16a570220fe
Revises: b028bca8c3a1
Create Date: 2026-10-28 00:00:00.000000

Stage 4's "full alert rules": each alert can be 'daily' or 'instant'
cadence, and 'email' or 'whatsapp' channel (whatsapp stored but not yet
delivered -- see backend/alerts/modals/alert.py's CADENCES/CHANNELS).
Existing rows default to 'daily'/'email', i.e. exactly today's behavior.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c16a570220fe'
down_revision = 'b028bca8c3a1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('alert')}
    if 'cadence' not in cols:
        op.add_column('alert', sa.Column('cadence', sa.String(length=20), nullable=False, server_default='daily'))
    if 'channel' not in cols:
        op.add_column('alert', sa.Column('channel', sa.String(length=20), nullable=False, server_default='email'))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('alert')}
    if 'channel' in cols:
        op.drop_column('alert', 'channel')
    if 'cadence' in cols:
        op.drop_column('alert', 'cadence')
