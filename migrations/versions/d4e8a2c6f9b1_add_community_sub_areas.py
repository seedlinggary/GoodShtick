"""add community.sub_areas

Revision ID: d4e8a2c6f9b1
Revises: b7c3e9a1d6f8
Create Date: 2026-11-01 00:00:00.000000

Curated neighborhoods within a Community (e.g. Beit Shemesh's Mishkafayim/
Ramat Shilo/Neve Shamir/Ramat Gimmel) -- a list of {"name": str,
"match": [str, ...]} dicts, defined by whoever manages that community (see
backend/business/modals/community.py's Community.sub_areas,
backend/business/routes/community.py's get_community()'s ?area= handling
and _validate_sub_areas()). Nullable, purely additive, nothing existing is
touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the column already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e8a2c6f9b1'
down_revision = 'b7c3e9a1d6f8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('community')}

    with op.batch_alter_table('community', schema=None) as batch_op:
        if 'sub_areas' not in columns:
            batch_op.add_column(sa.Column('sub_areas', sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('community')}

    with op.batch_alter_table('community', schema=None) as batch_op:
        if 'sub_areas' in columns:
            batch_op.drop_column('sub_areas')
