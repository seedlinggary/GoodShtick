"""support multiple categories per news article

Revision ID: a3a83693edd7
Revises: 7e82bc891b0c
Create Date: 2026-11-17 19:38:09.627029

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a3a83693edd7'
down_revision = '7e82bc891b0c'
branch_labels = None
depends_on = None


def upgrade():
    # Additive only -- the old `category` column is left in place (unused
    # by the app from here on) rather than dropped in the same migration,
    # since dropping a column needs a deliberate, separate confirmation
    # even on an empty table. Drop it in a later migration once that's
    # actually wanted.
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.add_column(sa.Column('categories', postgresql.ARRAY(sa.String(length=40)), server_default='{}', nullable=False))


def downgrade():
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.drop_column('categories')
