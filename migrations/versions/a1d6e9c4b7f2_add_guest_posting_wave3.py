"""guest posting wave 3 -- estates, business, marketplace, community, group buy

Revision ID: a1d6e9c4b7f2
Revises: f3c7b2e5a8d1
Create Date: 2026-11-02 00:00:00.000002

Adds guest_email/guest_phone/guest_manage_token (same shape as wave 2) PLUS
a new approved_to_publish column to EstatesListing/Business/
MarketplaceListing/Community/EstatesGroupBuy -- these 5 go live immediately
today with no moderation gate at all, unlike Tachlis/Shtick/NewsArticle.

CRITICAL: every EXISTING row in these 5 tables is already live, real,
previously-approved content -- the new column is backfilled to True for
every existing row in this same migration, not left NULL, so nothing that's
already public silently looks "pending" the moment any route starts
filtering on this column. Only a NEW guest submission is ever inserted
with approved_to_publish=None; every existing logged-in create path keeps
setting it True immediately, same as it implicitly always has.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the columns already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1d6e9c4b7f2'
down_revision = 'f3c7b2e5a8d1'
branch_labels = None
depends_on = None

TABLES = ('estates_listing', 'business', 'marketplace_listing', 'community', 'estates_group_buy')


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in TABLES:
        columns = {c['name'] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'guest_email' not in columns:
                batch_op.add_column(sa.Column('guest_email', sa.String(length=150), nullable=True))
            if 'guest_phone' not in columns:
                batch_op.add_column(sa.Column('guest_phone', sa.String(length=40), nullable=True))
            if 'guest_manage_token' not in columns:
                batch_op.add_column(sa.Column('guest_manage_token', sa.String(length=64), nullable=True))
            if 'approved_to_publish' not in columns:
                batch_op.add_column(sa.Column('approved_to_publish', sa.Boolean(), nullable=True))

        # Backfill existing rows to True -- see module docstring. Only
        # rows that are still NULL get touched, so re-running this is safe
        # and never overwrites a real pending/rejected guest row that may
        # have landed by the time this is re-run.
        if 'approved_to_publish' not in columns:
            op.execute(f'UPDATE {table} SET approved_to_publish = TRUE WHERE approved_to_publish IS NULL')

    # Fresh inspector -- reusing the one from above can return a stale
    # pre-add_column snapshot within the same transaction (confirmed live
    # in an earlier migration this session).
    inspector = sa.inspect(bind)
    for table in TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            ix_token = f'ix_{table}_guest_manage_token'
            if ix_token not in existing_indexes:
                batch_op.create_index(batch_op.f(ix_token), ['guest_manage_token'], unique=True)
            ix_approved = f'ix_{table}_approved_to_publish'
            if ix_approved not in existing_indexes:
                batch_op.create_index(batch_op.f(ix_approved), ['approved_to_publish'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if f'ix_{table}_approved_to_publish' in existing_indexes:
                batch_op.drop_index(batch_op.f(f'ix_{table}_approved_to_publish'))
            if f'ix_{table}_guest_manage_token' in existing_indexes:
                batch_op.drop_index(batch_op.f(f'ix_{table}_guest_manage_token'))

    for table in TABLES:
        columns = {c['name'] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'approved_to_publish' in columns:
                batch_op.drop_column('approved_to_publish')
            if 'guest_manage_token' in columns:
                batch_op.drop_column('guest_manage_token')
            if 'guest_phone' in columns:
                batch_op.drop_column('guest_phone')
            if 'guest_email' in columns:
                batch_op.drop_column('guest_email')
