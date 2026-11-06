"""add business_site table

Revision ID: a1c5e8f2b9d4
Revises: d4a7c2e9f1b3
Create Date: 2026-11-05 00:00:00.000000

Phase 0 of the business-owner website builder (see plan file
tender-inventing-teapot.md). One new table, BusinessSite, 1:1 with
Business -- everything else in this feature (pages, products, bookings,
payments) is a separate table in a later migration, gated through this
one's enabled_modules JSON column. Purely additive: no existing table or
column is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c5e8f2b9d4'
down_revision = 'd4a7c2e9f1b3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'business_site' not in existing_tables:
        op.create_table(
            'business_site',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('subdomain', sa.String(length=160), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
            sa.Column('enabled_modules', sa.JSON(), nullable=False),
            sa.Column('theme', sa.JSON(), nullable=True),
            sa.Column('custom_domain', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('published_at', sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('business_site')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('business_site')}

    with op.batch_alter_table('business_site', schema=None) as batch_op:
        if 'ix_business_site_business_id' not in existing_indexes and 'uq_business_site_business_id' not in existing_uniques:
            batch_op.create_index(batch_op.f('ix_business_site_business_id'), ['business_id'], unique=True)
        if 'ix_business_site_subdomain' not in existing_indexes and 'uq_business_site_subdomain' not in existing_uniques:
            batch_op.create_index(batch_op.f('ix_business_site_subdomain'), ['subdomain'], unique=True)
        if 'ix_business_site_status' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_business_site_status'), ['status'], unique=False)
        if 'uq_business_site_custom_domain' not in existing_uniques:
            batch_op.create_unique_constraint(batch_op.f('uq_business_site_custom_domain'), ['custom_domain'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'business_site' in set(inspector.get_table_names()):
        op.drop_table('business_site')
