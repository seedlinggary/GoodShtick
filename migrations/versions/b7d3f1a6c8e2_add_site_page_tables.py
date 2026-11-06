"""add site_page and site_page_version tables

Revision ID: b7d3f1a6c8e2
Revises: a1c5e8f2b9d4
Create Date: 2026-11-05 00:00:01.000000

Phase 2 of the business-owner website builder (see plan file
tender-inventing-teapot.md): the page-builder's storage. SitePage is a
page's stable identity (slug/title/SEO); SitePageVersion is append-only
content (one row per draft save, is_published marking the live one) so a
draft edit never affects what the public sees until Publish. Purely
additive -- no existing table or column is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the tables already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d3f1a6c8e2'
down_revision = 'a1c5e8f2b9d4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'site_page' not in existing_tables:
        op.create_table(
            'site_page',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_site_id', sa.Integer(), sa.ForeignKey('business_site.id'), nullable=False),
            sa.Column('slug', sa.String(length=160), nullable=False),
            sa.Column('title', sa.String(length=150), nullable=False),
            sa.Column('is_home', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
            sa.Column('seo_title', sa.String(length=70), nullable=True),
            sa.Column('seo_description', sa.String(length=200), nullable=True),
            sa.Column('seo_og_image', sa.String(length=300), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    if 'site_page_version' not in existing_tables:
        op.create_table(
            'site_page_version',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('page_id', sa.Integer(), sa.ForeignKey('site_page.id'), nullable=False),
            sa.Column('sections', sa.JSON(), nullable=False),
            sa.Column('is_published', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_by', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('site_page')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('site_page')}
    with op.batch_alter_table('site_page', schema=None) as batch_op:
        if 'ix_site_page_business_site_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_page_business_site_id'), ['business_site_id'], unique=False)
        if 'ix_site_page_status' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_page_status'), ['status'], unique=False)
        if 'uq_site_page_site_slug' not in existing_uniques:
            batch_op.create_unique_constraint('uq_site_page_site_slug', ['business_site_id', 'slug'])

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('site_page_version')}
    with op.batch_alter_table('site_page_version', schema=None) as batch_op:
        if 'ix_site_page_version_page_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_page_version_page_id'), ['page_id'], unique=False)
        if 'ix_site_page_version_is_published' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_page_version_is_published'), ['is_published'], unique=False)
        if 'ix_site_page_version_created_at' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_page_version_created_at'), ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if 'site_page_version' in existing_tables:
        op.drop_table('site_page_version')
    if 'site_page' in existing_tables:
        op.drop_table('site_page')
