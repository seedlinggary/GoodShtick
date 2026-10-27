"""add source_posted_at (estates + tachlis) and tachlis category/remote

Revision ID: f3a7c1e9b542
Revises: b2e4f8a1c9d3
Create Date: 2026-10-27 00:00:00.000000

Stage 1 of gut_next_level_agent.md ("Real Newest sort" + "Filters that
matter"):

- `source_posted_at` on estates_listing and tachlis_post: the time a listing
  or post actually went up in its source WhatsApp group, distinct from
  pub_date (when it was added to this DB). NULL on every existing row and on
  anything posted directly on-site -- "newest" sorting falls back to
  pub_date whenever this is NULL (see both routes' list queries), so this is
  purely additive and changes no existing ordering until it's populated.
- `category`/`remote` on tachlis_post: new optional job-board filters: free-
  text category (e.g. "Tech", "Healthcare") and whether the job is remote.
  Both NULL on every existing row, same "not specified" convention as
  EstatesListing.is_agent.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a7c1e9b542'
down_revision = 'b2e4f8a1c9d3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    estates_columns = {c['name'] for c in inspector.get_columns('estates_listing')}
    with op.batch_alter_table('estates_listing', schema=None) as batch_op:
        if 'source_posted_at' not in estates_columns:
            batch_op.add_column(sa.Column('source_posted_at', sa.DateTime(), nullable=True))
            batch_op.create_index('ix_estates_listing_source_posted_at', ['source_posted_at'])

    tachlis_columns = {c['name'] for c in inspector.get_columns('tachlis_post')}
    with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
        if 'source_posted_at' not in tachlis_columns:
            batch_op.add_column(sa.Column('source_posted_at', sa.DateTime(), nullable=True))
            batch_op.create_index('ix_tachlis_post_source_posted_at', ['source_posted_at'])
        if 'category' not in tachlis_columns:
            batch_op.add_column(sa.Column('category', sa.String(length=60), nullable=True))
            batch_op.create_index('ix_tachlis_post_category', ['category'])
        if 'remote' not in tachlis_columns:
            batch_op.add_column(sa.Column('remote', sa.Boolean(), nullable=True))
            batch_op.create_index('ix_tachlis_post_remote', ['remote'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tachlis_columns = {c['name'] for c in inspector.get_columns('tachlis_post')}
    with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
        if 'remote' in tachlis_columns:
            batch_op.drop_index('ix_tachlis_post_remote')
            batch_op.drop_column('remote')
        if 'category' in tachlis_columns:
            batch_op.drop_index('ix_tachlis_post_category')
            batch_op.drop_column('category')
        if 'source_posted_at' in tachlis_columns:
            batch_op.drop_index('ix_tachlis_post_source_posted_at')
            batch_op.drop_column('source_posted_at')

    estates_columns = {c['name'] for c in inspector.get_columns('estates_listing')}
    with op.batch_alter_table('estates_listing', schema=None) as batch_op:
        if 'source_posted_at' in estates_columns:
            batch_op.drop_index('ix_estates_listing_source_posted_at')
            batch_op.drop_column('source_posted_at')
