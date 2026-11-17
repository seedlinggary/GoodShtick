"""add news_ticker_item table

Revision ID: e3d1f37410b8
Revises: a3a83693edd7
Create Date: 2026-11-17 20:38:05.953120

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3d1f37410b8'
down_revision = 'a3a83693edd7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('news_ticker_item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('text', sa.String(length=240), nullable=False),
    sa.Column('link_url', sa.String(length=500), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['user.public_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('news_ticker_item', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_news_ticker_item_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_news_ticker_item_is_active'), ['is_active'], unique=False)


def downgrade():
    with op.batch_alter_table('news_ticker_item', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_news_ticker_item_is_active'))
        batch_op.drop_index(batch_op.f('ix_news_ticker_item_created_at'))

    op.drop_table('news_ticker_item')
