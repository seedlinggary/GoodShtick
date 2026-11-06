"""add business_site nav_links/footer_text/footer_links columns

Revision ID: a4c7e1f9b2d6
Revises: f1b8d4e7a3c5
Create Date: 2026-11-05 00:00:06.000000

Phase 8/9 of the business-owner website builder (see plan file
tender-inventing-teapot.md): site-wide chrome content (nav links, footer)
that applies on every page -- "add something for all pages". theme itself
is an existing column (already added in Phase 0), just now validated
against a real registry instead of accepting any dict. Purely additive.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether these columns already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4c7e1f9b2d6'
down_revision = 'f1b8d4e7a3c5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('business_site')}

    with op.batch_alter_table('business_site', schema=None) as batch_op:
        if 'nav_links' not in columns:
            batch_op.add_column(sa.Column('nav_links', sa.JSON(), nullable=True))
        if 'footer_text' not in columns:
            batch_op.add_column(sa.Column('footer_text', sa.String(length=300), nullable=True))
        if 'footer_links' not in columns:
            batch_op.add_column(sa.Column('footer_links', sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('business_site')}

    with op.batch_alter_table('business_site', schema=None) as batch_op:
        if 'footer_links' in columns:
            batch_op.drop_column('footer_links')
        if 'footer_text' in columns:
            batch_op.drop_column('footer_text')
        if 'nav_links' in columns:
            batch_op.drop_column('nav_links')
