"""add label_style to nonprofit_form_field

Revision ID: 14a92a73db77
Revises: 93a88a64bd62
Create Date: 2026-11-10 23:33:50.185858

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '14a92a73db77'
down_revision = '93a88a64bd62'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('nonprofit_form_field', schema=None) as batch_op:
        batch_op.add_column(sa.Column('label_style', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('nonprofit_form_field', schema=None) as batch_op:
        batch_op.drop_column('label_style')
