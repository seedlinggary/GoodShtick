"""widen news_article category column for custom topics

Revision ID: 7e82bc891b0c
Revises: c23eee5d6301
Create Date: 2026-11-17 19:16:18.150564

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7e82bc891b0c'
down_revision = 'c23eee5d6301'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.alter_column('category',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=40),
               existing_nullable=False,
               existing_server_default=sa.text("'other'::character varying"))


def downgrade():
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.alter_column('category',
               existing_type=sa.String(length=40),
               type_=sa.VARCHAR(length=20),
               existing_nullable=False,
               existing_server_default=sa.text("'other'::character varying"))
