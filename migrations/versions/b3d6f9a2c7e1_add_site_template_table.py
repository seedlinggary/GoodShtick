"""add site_template table

Revision ID: b3d6f9a2c7e1
Revises: a4c7e1f9b2d6
Create Date: 2026-11-05 00:00:07.000000

Phase 10 of the business-owner website builder (see plan file
tender-inventing-teapot.md): starter templates. Purely additive -- no
existing table or column is touched.

Seeding the 5 defaults is deliberately NOT done here -- an ORM query
(SiteTemplate.query, used by seed_default_templates's idempotency check)
against db.session sees a different, not-yet-committed connection than
this migration's own op.get_bind() DDL within the same transactional
migration, so "create the table, then ORM-query it" in one upgrade()
reliably fails with UndefinedTable (confirmed live against prod). Run
seed_default_templates() as a separate one-off script AFTER this
migration has committed instead.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3d6f9a2c7e1'
down_revision = 'a4c7e1f9b2d6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'site_template' not in existing_tables:
        op.create_table(
            'site_template',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('description', sa.String(length=300), nullable=True),
            sa.Column('category', sa.String(length=40), nullable=True),
            sa.Column('preview_image', sa.String(length=500), nullable=True),
            sa.Column('theme', sa.JSON(), nullable=True),
            sa.Column('home_sections', sa.JSON(), nullable=False),
            sa.Column('nav_links', sa.JSON(), nullable=True),
            sa.Column('footer_text', sa.String(length=300), nullable=True),
            sa.Column('is_system_default', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_by', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('site_template')}
    with op.batch_alter_table('site_template', schema=None) as batch_op:
        if 'ix_site_template_active' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_site_template_active'), ['active'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'site_template' in set(inspector.get_table_names()):
        op.drop_table('site_template')
