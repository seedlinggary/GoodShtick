"""add community_data_cache table

Revision ID: f4b6d8e2a5c7
Revises: e1a2c9f7b3d4
Create Date: 2026-10-31 00:00:00.000001

Generic cache for the Business domain's own slow/cacheable external calls --
today that's GPT cost-of-living estimates (see
backend/business/modals/community.py's CommunityDataCache,
backend/business/routes/community.py's get_cost_of_living), keyed by a
string like 'col:<slug>'. Same shape as backend/finance/modals/finance.py's
FinanceDataCache, duplicated per-domain rather than cross-imported (this
codebase's established convention). Brand-new table, nothing existing is
touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table/indexes already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4b6d8e2a5c7'
down_revision = 'e1a2c9f7b3d4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'community_data_cache' not in inspector.get_table_names():
        op.create_table(
            'community_data_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            # unique=True here (matching the model's unique=True, index=True
            # on this column) already creates the one unique index backing
            # it -- no separate UniqueConstraint/create_index needed on top.
            sa.Column('cache_key', sa.String(length=120), nullable=False, unique=True),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column('fetched_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'community_data_cache' in inspector.get_table_names():
        op.drop_table('community_data_cache')
