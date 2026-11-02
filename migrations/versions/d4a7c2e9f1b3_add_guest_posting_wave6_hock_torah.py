"""guest posting wave 6 -- hock posts, torah posts

Revision ID: d4a7c2e9f1b3
Revises: c9d3a6e8f1b4
Create Date: 2026-11-02 00:00:00.000005

The Phase 2 the original plan deliberately deferred: Hock and Torah
top-level posts. Both needed real schema work beyond the earlier waves'
copy-paste shape.

HockPost already has an approved_to_publish column, but as a NOT NULL
Boolean(default=True) takedown switch, not a three-state pending gate --
relaxed to nullable here so a guest post can land at None the same way
every other domain's guest row does; existing rows are untouched (every
one is already True). user_id also relaxed NOT NULL -> nullable (a guest
post has no user), same as every prior wave's comment/post tables.

TorahPost had NO moderation gate at all -- a brand new approved_to_publish
column is added. CRITICAL: every existing row is already live, previously
-published content, so it's backfilled to True in this same migration,
not left NULL, exactly like wave 3's five tables that were in the same
situation. created_by was already nullable (never had a gate to begin
with), so no change needed there.

Both tables get the usual guest_email/guest_phone/guest_manage_token
trio. Guarded with inspector checks the same way every migration in this
chain is, so this is safe to run whether the columns already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4a7c2e9f1b3'
down_revision = 'c9d3a6e8f1b4'
branch_labels = None
depends_on = None

GUEST_FIELD_TABLES = ('hock_post', 'torah_post')


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in GUEST_FIELD_TABLES:
        columns = {c['name']: c for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'guest_email' not in columns:
                batch_op.add_column(sa.Column('guest_email', sa.String(length=150), nullable=True))
            if 'guest_phone' not in columns:
                batch_op.add_column(sa.Column('guest_phone', sa.String(length=40), nullable=True))
            if 'guest_manage_token' not in columns:
                batch_op.add_column(sa.Column('guest_manage_token', sa.String(length=64), nullable=True))

    # hock_post.approved_to_publish: NOT NULL -> nullable. Every existing
    # row is already True, so no backfill needed -- this only widens what's
    # allowed going forward.
    hock_cols = {c['name']: c for c in inspector.get_columns('hock_post')}
    with op.batch_alter_table('hock_post', schema=None) as batch_op:
        if hock_cols.get('approved_to_publish', {}).get('nullable') is False:
            batch_op.alter_column('approved_to_publish', existing_type=sa.Boolean(), nullable=True)
        if hock_cols.get('user_id', {}).get('nullable') is False:
            batch_op.alter_column('user_id', existing_type=sa.String(length=50), nullable=True)

    # torah_post.approved_to_publish: brand new column -- backfill existing
    # rows to True (see module docstring) so nothing already-public silently
    # looks "pending" the moment list_posts/get_post start filtering on it.
    torah_cols = {c['name'] for c in inspector.get_columns('torah_post')}
    if 'approved_to_publish' not in torah_cols:
        with op.batch_alter_table('torah_post', schema=None) as batch_op:
            batch_op.add_column(sa.Column('approved_to_publish', sa.Boolean(), nullable=True))
        op.execute('UPDATE torah_post SET approved_to_publish = TRUE WHERE approved_to_publish IS NULL')

    # Fresh inspector -- reusing the one from above can return a stale
    # pre-add_column snapshot within the same transaction (confirmed live
    # in earlier migrations this session).
    inspector = sa.inspect(bind)
    for table in GUEST_FIELD_TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        ix_token = f'ix_{table}_guest_manage_token'
        if ix_token not in existing_indexes:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.create_index(batch_op.f(ix_token), ['guest_manage_token'], unique=True)

    torah_indexes = {ix['name'] for ix in inspector.get_indexes('torah_post')}
    if 'ix_torah_post_approved_to_publish' not in torah_indexes:
        with op.batch_alter_table('torah_post', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_torah_post_approved_to_publish'), ['approved_to_publish'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    torah_indexes = {ix['name'] for ix in inspector.get_indexes('torah_post')}
    if 'ix_torah_post_approved_to_publish' in torah_indexes:
        with op.batch_alter_table('torah_post', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_torah_post_approved_to_publish'))

    for table in GUEST_FIELD_TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        ix_token = f'ix_{table}_guest_manage_token'
        if ix_token in existing_indexes:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.drop_index(batch_op.f(ix_token))

    torah_cols = {c['name'] for c in inspector.get_columns('torah_post')}
    if 'approved_to_publish' in torah_cols:
        with op.batch_alter_table('torah_post', schema=None) as batch_op:
            batch_op.drop_column('approved_to_publish')

    hock_cols = {c['name']: c for c in inspector.get_columns('hock_post')}
    with op.batch_alter_table('hock_post', schema=None) as batch_op:
        if hock_cols.get('user_id', {}).get('nullable') is True:
            batch_op.alter_column('user_id', existing_type=sa.String(length=50), nullable=False)
        if hock_cols.get('approved_to_publish', {}).get('nullable') is True:
            batch_op.alter_column('approved_to_publish', existing_type=sa.Boolean(), nullable=False)

    for table in GUEST_FIELD_TABLES:
        columns = {c['name'] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'guest_manage_token' in columns:
                batch_op.drop_column('guest_manage_token')
            if 'guest_phone' in columns:
                batch_op.drop_column('guest_phone')
            if 'guest_email' in columns:
                batch_op.drop_column('guest_email')
