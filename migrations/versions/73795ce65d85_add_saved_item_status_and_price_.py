"""add saved item status and price tracking

Revision ID: 73795ce65d85
Revises: c16a570220fe
Create Date: 2026-10-28 00:00:00.000000

Stage 4's "saved items with status" (status/note) and the price-drop /
back-on-market sweep's own snapshot columns (notified_price/was_active) on
EstatesListingLike. Existing rows get status='saved', was_active=True,
notified_price=NULL -- the sweep treats a NULL notified_price as "no
baseline yet" and just sets one on its first pass, with no notification.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '73795ce65d85'
down_revision = 'c16a570220fe'
branch_labels = None
depends_on = None

NEW_COLUMNS = ['status', 'note', 'notified_price', 'was_active']


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('estates_listing_like')}

    if 'status' not in cols:
        op.add_column('estates_listing_like', sa.Column('status', sa.String(length=20), nullable=False, server_default='saved'))
    if 'note' not in cols:
        op.add_column('estates_listing_like', sa.Column('note', sa.String(length=500), nullable=True))
    if 'notified_price' not in cols:
        op.add_column('estates_listing_like', sa.Column('notified_price', sa.Float(), nullable=True))
    if 'was_active' not in cols:
        op.add_column('estates_listing_like', sa.Column('was_active', sa.Boolean(), nullable=False, server_default='true'))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('estates_listing_like')}
    for col in NEW_COLUMNS:
        if col in cols:
            op.drop_column('estates_listing_like', col)
