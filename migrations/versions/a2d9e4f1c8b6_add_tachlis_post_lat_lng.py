"""add tachlis_post.lat and tachlis_post.lng

Revision ID: a2d9e4f1c8b6
Revises: f4b6d8e2a5c7
Create Date: 2026-10-31 00:00:00.000002

Geocoded from a post's `location` (best-effort, via Photon -- see
backend/tachlis/routes/tachlis_post.py's _geocode) so Community Profile
pages can find nearby job posts within an approximate radius. Populated
automatically on create/edit going forward; existing posts stay NULL until
next edited -- not backfilled in this pass. Nullable, purely additive,
nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the columns/indexes already exist or
not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2d9e4f1c8b6'
down_revision = 'f4b6d8e2a5c7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('tachlis_post')}
    indexes = {ix['name'] for ix in inspector.get_indexes('tachlis_post')}

    with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
        if 'lat' not in columns:
            batch_op.add_column(sa.Column('lat', sa.Float(), nullable=True))
        if 'lng' not in columns:
            batch_op.add_column(sa.Column('lng', sa.Float(), nullable=True))
        if 'ix_tachlis_post_lat' not in indexes:
            batch_op.create_index(batch_op.f('ix_tachlis_post_lat'), ['lat'], unique=False)
        if 'ix_tachlis_post_lng' not in indexes:
            batch_op.create_index(batch_op.f('ix_tachlis_post_lng'), ['lng'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('tachlis_post')}
    indexes = {ix['name'] for ix in inspector.get_indexes('tachlis_post')}

    with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
        if 'ix_tachlis_post_lng' in indexes:
            batch_op.drop_index(batch_op.f('ix_tachlis_post_lng'))
        if 'ix_tachlis_post_lat' in indexes:
            batch_op.drop_index(batch_op.f('ix_tachlis_post_lat'))
        if 'lng' in columns:
            batch_op.drop_column('lng')
        if 'lat' in columns:
            batch_op.drop_column('lat')
