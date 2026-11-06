"""add customer_note table and order.invoice_number column

Revision ID: f1b8d4e7a3c5
Revises: e6a9c3f2d8b1
Create Date: 2026-11-05 00:00:05.000000

Phase 6 of the business-owner website builder (see plan file
tender-inventing-teapot.md): the CRM's one genuinely new piece of data
(CustomerNote) and the column that turns an existing Order into a
receipt/invoice (see commerce.py's Order.invoice_number docstring for why
there's no separate Invoice table). Purely additive -- no existing column
is touched beyond the one new nullable column on order.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether these already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1b8d4e7a3c5'
down_revision = 'e6a9c3f2d8b1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'customer_note' not in existing_tables:
        op.create_table(
            'customer_note',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('identity_key', sa.String(length=200), nullable=False),
            sa.Column('note', sa.Text(), nullable=False),
            sa.Column('created_by', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    order_columns = {c['name'] for c in inspector.get_columns('order')}
    if 'invoice_number' not in order_columns:
        with op.batch_alter_table('order', schema=None) as batch_op:
            batch_op.add_column(sa.Column('invoice_number', sa.String(length=32), nullable=True))

    inspector = sa.inspect(bind)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('customer_note')}
    with op.batch_alter_table('customer_note', schema=None) as batch_op:
        if 'ix_customer_note_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_customer_note_business_id'), ['business_id'], unique=False)
        if 'ix_customer_note_identity_key' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_customer_note_identity_key'), ['identity_key'], unique=False)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('order')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('order')}
    with op.batch_alter_table('order', schema=None) as batch_op:
        if 'ix_order_invoice_number' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_order_invoice_number'), ['invoice_number'], unique=False)
        if 'uq_order_invoice_number' not in existing_uniques:
            batch_op.create_unique_constraint('uq_order_invoice_number', ['invoice_number'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    order_columns = {c['name'] for c in inspector.get_columns('order')}
    if 'invoice_number' in order_columns:
        with op.batch_alter_table('order', schema=None) as batch_op:
            batch_op.drop_column('invoice_number')

    if 'customer_note' in set(inspector.get_table_names()):
        op.drop_table('customer_note')
