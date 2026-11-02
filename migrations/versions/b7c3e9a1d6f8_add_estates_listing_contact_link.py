"""add estates_listing.contact_link

Revision ID: b7c3e9a1d6f8
Revises: a2d9e4f1c8b6
Create Date: 2026-11-01 00:00:00.000000

A link in place of (or alongside) email/phone/WhatsApp as a listing's
contact method -- for listings sourced from another site that wants to be
contacted through its own listing page/form rather than directly (see
backend/estates/routes/estates.py's _validate_listing_body, which now
accepts contact_link as a standalone valid contact method). Nullable,
purely additive, nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the column already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c3e9a1d6f8'
down_revision = 'a2d9e4f1c8b6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('estates_listing')}

    with op.batch_alter_table('estates_listing', schema=None) as batch_op:
        if 'contact_link' not in columns:
            batch_op.add_column(sa.Column('contact_link', sa.String(length=500), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('estates_listing')}

    with op.batch_alter_table('estates_listing', schema=None) as batch_op:
        if 'contact_link' in columns:
            batch_op.drop_column('contact_link')
