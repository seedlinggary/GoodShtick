"""replace ad.placement with multi-value ad.placements

Revision ID: b2e4f8a1c9d3
Revises: d82eb53cdf7c
Create Date: 2026-10-26 00:00:00.000000

Lets one ad target one or many pages/placements across any site instead of
exactly one. `placements` is a comma-separated list of VALID_PLACEMENTS
values (see backend/ads/routes/ads.py); NULL/empty means "every placement",
matching this model's own existing null-means-unrestricted convention for
target_age_min/target_gender/target_countries. Existing ads are left NULL
here on purpose -- that already means "all pages" per that convention, which
is the explicitly requested default for ads that existed before this change.

Guarded the same way 7a1c9f2e4b6d (which first created this table) is, so
this is safe to run whether `placement` already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2e4f8a1c9d3'
down_revision = 'd82eb53cdf7c'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ad_columns = {c['name'] for c in inspector.get_columns('ad')}

    with op.batch_alter_table('ad', schema=None) as batch_op:
        if 'placements' not in ad_columns:
            batch_op.add_column(sa.Column('placements', sa.Text(), nullable=True))
        if 'placement' in ad_columns:
            batch_op.drop_column('placement')


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ad_columns = {c['name'] for c in inspector.get_columns('ad')}

    with op.batch_alter_table('ad', schema=None) as batch_op:
        if 'placement' not in ad_columns:
            batch_op.add_column(sa.Column('placement', sa.String(length=30), nullable=True))
        if 'placements' in ad_columns:
            batch_op.drop_column('placements')
