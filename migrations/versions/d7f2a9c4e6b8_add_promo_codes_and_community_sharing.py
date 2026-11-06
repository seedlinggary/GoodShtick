"""add promo codes, product sale price, and community-sharing toggles

Revision ID: d7f2a9c4e6b8
Revises: c5e8a3f1b9d4
Create Date: 2026-11-05 00:00:09.000000

Second wave of owner-facing site-builder requests (see plan file
tender-inventing-teapot.md for the original phases this extends):
  - Product.compare_at_price_cents -- lets an owner mark an item "on sale"
    (a struck-through "was" price) without needing a code.
  - A new promo_code table -- owner-defined discount codes, applied at
    storefront checkout (business_site_public.py's submit_checkout).
  - Order.promo_code_id / discount_cents -- which code (if any) was used
    on a given order, and how much it took off.
  - BusinessSite.share_products_with_community /
    share_deals_with_community -- two new, DEFAULT-ON toggles (an
    explicit product request: opt OUT, not opt in) controlling whether
    promo_sync.py posts a site's products/active codes onto the main Gut
    Community feed.

Schema only, same reasoning as b3d6f9a2c7e1's own docstring for why no ORM
data seeding belongs in the same migration as DDL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7f2a9c4e6b8'
down_revision = 'c5e8a3f1b9d4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── business_site: two new default-true toggles ────────────────────
    existing_site_cols = {c['name'] for c in inspector.get_columns('business_site')}
    with op.batch_alter_table('business_site', schema=None) as batch_op:
        if 'share_products_with_community' not in existing_site_cols:
            batch_op.add_column(sa.Column(
                'share_products_with_community', sa.Boolean(), nullable=False, server_default='true'))
        if 'share_deals_with_community' not in existing_site_cols:
            batch_op.add_column(sa.Column(
                'share_deals_with_community', sa.Boolean(), nullable=False, server_default='true'))

    # ── product: optional "was" price ──────────────────────────────────
    existing_product_cols = {c['name'] for c in inspector.get_columns('product')}
    with op.batch_alter_table('product', schema=None) as batch_op:
        if 'compare_at_price_cents' not in existing_product_cols:
            batch_op.add_column(sa.Column('compare_at_price_cents', sa.Integer(), nullable=True))

    # ── promo_code (new table) ──────────────────────────────────────────
    existing_tables = set(inspector.get_table_names())
    if 'promo_code' not in existing_tables:
        op.create_table(
            'promo_code',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('code', sa.String(length=40), nullable=False),
            sa.Column('discount_type', sa.String(length=10), nullable=False),
            sa.Column('amount', sa.Integer(), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('max_redemptions', sa.Integer(), nullable=True),
            sa.Column('redemption_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('min_subtotal_cents', sa.Integer(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('promo_code')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('promo_code')}
    with op.batch_alter_table('promo_code', schema=None) as batch_op:
        if 'ix_promo_code_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_promo_code_business_id'), ['business_id'], unique=False)
        if 'ix_promo_code_active' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_promo_code_active'), ['active'], unique=False)
        if 'uq_promo_code_business_code' not in existing_uniques:
            batch_op.create_unique_constraint('uq_promo_code_business_code', ['business_id', 'code'])

    # ── order: which code was used, and how much it took off ───────────
    existing_order_cols = {c['name'] for c in inspector.get_columns('order')}
    with op.batch_alter_table('order', schema=None) as batch_op:
        if 'promo_code_id' not in existing_order_cols:
            batch_op.add_column(sa.Column('promo_code_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_order_promo_code_id', 'promo_code', ['promo_code_id'], ['id'], ondelete='SET NULL')
        if 'discount_cents' not in existing_order_cols:
            batch_op.add_column(sa.Column('discount_cents', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_order_cols = {c['name'] for c in inspector.get_columns('order')}
    with op.batch_alter_table('order', schema=None) as batch_op:
        if 'promo_code_id' in existing_order_cols:
            batch_op.drop_constraint('fk_order_promo_code_id', type_='foreignkey')
            batch_op.drop_column('promo_code_id')
        if 'discount_cents' in existing_order_cols:
            batch_op.drop_column('discount_cents')

    if 'promo_code' in set(inspector.get_table_names()):
        op.drop_table('promo_code')

    existing_product_cols = {c['name'] for c in inspector.get_columns('product')}
    with op.batch_alter_table('product', schema=None) as batch_op:
        if 'compare_at_price_cents' in existing_product_cols:
            batch_op.drop_column('compare_at_price_cents')

    existing_site_cols = {c['name'] for c in inspector.get_columns('business_site')}
    with op.batch_alter_table('business_site', schema=None) as batch_op:
        if 'share_deals_with_community' in existing_site_cols:
            batch_op.drop_column('share_deals_with_community')
        if 'share_products_with_community' in existing_site_cols:
            batch_op.drop_column('share_products_with_community')
