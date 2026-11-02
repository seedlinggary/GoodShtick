"""add marketplace tables

Revision ID: c5f1a7e3b9d2
Revises: d4e8a2c6f9b1
Create Date: 2026-11-01 00:00:00.000000

Community Marketplace (buy/sell/trade/giveaway) -- a new, self-contained
feature, so all 3 tables ship together in one migration rather than the
incremental single-column style used elsewhere this session (see
backend/marketplace/modals/marketplace.py's MarketplaceListing/
MarketplaceListingPhoto/MarketplaceListingLike). Brand-new tables, nothing
existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the tables/indexes already exist or
not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5f1a7e3b9d2'
down_revision = 'd4e8a2c6f9b1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'marketplace_listing' not in existing_tables:
        op.create_table(
            'marketplace_listing',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(length=170), nullable=False),
            sa.Column('title', sa.String(length=150), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('category', sa.String(length=30), nullable=False),
            sa.Column('subcategory', sa.String(length=60), nullable=True),
            sa.Column('condition', sa.String(length=20), nullable=True),
            sa.Column('price', sa.Float(), nullable=True),
            sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'),
            sa.Column('is_free', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('ships', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('address', sa.String(length=300), nullable=True),
            sa.Column('city', sa.String(length=120), nullable=True),
            sa.Column('state', sa.String(length=80), nullable=True),
            sa.Column('country', sa.String(length=80), nullable=True),
            sa.Column('lat', sa.Float(), nullable=True),
            sa.Column('lng', sa.Float(), nullable=True),
            sa.Column('contact_name', sa.String(length=150), nullable=True),
            sa.Column('contact_email', sa.String(length=150), nullable=True),
            sa.Column('contact_phone', sa.String(length=40), nullable=True),
            sa.Column('contact_whatsapp', sa.String(length=40), nullable=True),
            sa.Column('contact_link', sa.String(length=500), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('renewed_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('views_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('contact_taps', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_by', sa.String(length=50), nullable=True),
            sa.Column('pub_date', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('slug', name='uq_marketplace_listing_slug'),
            sa.ForeignKeyConstraint(['created_by'], ['user.public_id'], name='fk_marketplace_listing_created_by_user'),
        )

    if 'marketplace_listing_photo' not in existing_tables:
        op.create_table(
            'marketplace_listing_photo',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('listing_id', sa.Integer(), nullable=False),
            sa.Column('filename', sa.String(length=300), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['listing_id'], ['marketplace_listing.id'], name='fk_marketplace_listing_photo_listing_id'),
        )

    if 'marketplace_listing_like' not in existing_tables:
        op.create_table(
            'marketplace_listing_like',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('listing_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='saved'),
            sa.Column('note', sa.String(length=500), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('listing_id', 'user_id', name='uq_marketplace_like_listing_user'),
            sa.ForeignKeyConstraint(['listing_id'], ['marketplace_listing.id'], name='fk_marketplace_listing_like_listing_id'),
            sa.ForeignKeyConstraint(['user_id'], ['user.public_id'], name='fk_marketplace_listing_like_user_id'),
        )

    # Fresh inspector -- reusing the one from above can return a stale,
    # pre-create_table snapshot of table existence within the same
    # transaction (confirmed live: it silently skipped every index below
    # on the very first run of this migration, since it still reported the
    # just-created tables as "not existing").
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table, cols in (
        # 'slug' deliberately excluded -- the UniqueConstraint above already
        # backs it with a unique index; a second non-unique index on the
        # same column would be redundant (same fix applied earlier this
        # session to community_data_cache.cache_key).
        ('marketplace_listing', ['category', 'subcategory', 'is_free', 'ships', 'city', 'country', 'lat', 'lng', 'created_by', 'pub_date', 'expires_at']),
        ('marketplace_listing_photo', ['listing_id']),
        ('marketplace_listing_like', ['listing_id', 'user_id']),
    ):
        if table not in existing_tables:
            continue
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            for col in cols:
                ix_name = f'ix_{table}_{col}'
                if ix_name not in existing_indexes:
                    batch_op.create_index(batch_op.f(ix_name), [col], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'marketplace_listing_like' in existing_tables:
        op.drop_table('marketplace_listing_like')
    if 'marketplace_listing_photo' in existing_tables:
        op.drop_table('marketplace_listing_photo')
    if 'marketplace_listing' in existing_tables:
        op.drop_table('marketplace_listing')
