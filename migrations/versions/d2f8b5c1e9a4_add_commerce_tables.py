"""add product, order, and order_item tables

Revision ID: d2f8b5c1e9a4
Revises: c9e4a2d7f3b6
Create Date: 2026-11-05 00:00:03.000000

Phase 4 of the business-owner website builder (see plan file
tender-inventing-teapot.md): a business's own product catalog and the
orders its storefront checkout creates. Purely additive -- no existing
table or column is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether these tables already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f8b5c1e9a4'
down_revision = 'c9e4a2d7f3b6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'product' not in existing_tables:
        op.create_table(
            'product',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('price_cents', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=3), nullable=False, server_default='usd'),
            sa.Column('images', sa.JSON(), nullable=True),
            sa.Column('sku', sa.String(length=64), nullable=True),
            sa.Column('inventory_count', sa.Integer(), nullable=True),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    if 'order' not in existing_tables:
        op.create_table(
            'order',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('payment_account_id', sa.Integer(), sa.ForeignKey('payment_account.id'), nullable=True),
            sa.Column('customer_user_id', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('guest_email', sa.String(length=150), nullable=True),
            sa.Column('guest_phone', sa.String(length=40), nullable=True),
            sa.Column('guest_manage_token', sa.String(length=64), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('subtotal_cents', sa.Integer(), nullable=False),
            sa.Column('platform_fee_cents', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_cents', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=3), nullable=False, server_default='usd'),
            sa.Column('external_payment_id', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    if 'order_item' not in existing_tables:
        op.create_table(
            'order_item',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id'), nullable=False),
            sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id', ondelete='SET NULL'), nullable=True),
            sa.Column('product_name', sa.String(length=150), nullable=False),
            sa.Column('unit_price_cents', sa.Integer(), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        )

    inspector = sa.inspect(bind)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('product')}
    with op.batch_alter_table('product', schema=None) as batch_op:
        if 'ix_product_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_product_business_id'), ['business_id'], unique=False)
        if 'ix_product_active' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_product_active'), ['active'], unique=False)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('order')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('order')}
    with op.batch_alter_table('order', schema=None) as batch_op:
        if 'ix_order_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_business_id'), ['business_id'], unique=False)
        if 'ix_order_customer_user_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_customer_user_id'), ['customer_user_id'], unique=False)
        if 'ix_order_status' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_status'), ['status'], unique=False)
        if 'ix_order_external_payment_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_external_payment_id'), ['external_payment_id'], unique=False)
        if 'ix_order_created_at' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_created_at'), ['created_at'], unique=False)
        if 'uq_order_guest_manage_token' not in existing_uniques:
            batch_op.create_unique_constraint('uq_order_guest_manage_token', ['guest_manage_token'])

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('order_item')}
    with op.batch_alter_table('order_item', schema=None) as batch_op:
        if 'ix_order_item_order_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_item_order_id'), ['order_id'], unique=False)
        if 'ix_order_item_product_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_item_product_id'), ['product_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if 'order_item' in existing_tables:
        op.drop_table('order_item')
    if 'order' in existing_tables:
        op.drop_table('order')
    if 'product' in existing_tables:
        op.drop_table('product')
