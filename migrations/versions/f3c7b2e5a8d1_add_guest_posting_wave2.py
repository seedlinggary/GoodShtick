"""guest posting wave 2 -- tachlis, shtick, news

Revision ID: f3c7b2e5a8d1
Revises: e8b4d1a9c3f6
Create Date: 2026-11-02 00:00:00.000001

Adds guest_email/guest_phone/guest_manage_token to TachlisPost/Shtick/
NewsArticle (the "post without an account" feature -- see
backend/guest/modals/guest_throttle.py for the shared rate-limit piece
that shipped just before this). Also relaxes TachlisPost.user_id from
NOT NULL to nullable -- the one real constraint change in this wave, and
backward-compatible since every existing row already has a real value.
Everything else here is purely additive. Shtick/NewsArticle need no
column changes beyond the 3 new guest fields: Shtick's approved_to_publish
already gates every post from everyone, and NewsArticle's already-nullable
created_by + already-nullable approved_to_publish just need a guest
submission to set approved_to_publish=None the way scraped articles
already do, which is route logic, not a schema change.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the columns already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3c7b2e5a8d1'
down_revision = 'e8b4d1a9c3f6'
branch_labels = None
depends_on = None

GUEST_FIELD_TABLES = ('tachlis_post', 'shtick', 'news_article')


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in GUEST_FIELD_TABLES:
        columns = {c['name'] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'guest_email' not in columns:
                batch_op.add_column(sa.Column('guest_email', sa.String(length=150), nullable=True))
            if 'guest_phone' not in columns:
                batch_op.add_column(sa.Column('guest_phone', sa.String(length=40), nullable=True))
            if 'guest_manage_token' not in columns:
                batch_op.add_column(sa.Column('guest_manage_token', sa.String(length=64), nullable=True))

    # TachlisPost.user_id: NOT NULL -> nullable (the one real constraint
    # change in this wave). Guarded by checking the live column's own
    # nullable flag rather than a fixed "did we already run" marker, so
    # this stays safe to re-run.
    tachlis_cols = {c['name']: c for c in inspector.get_columns('tachlis_post')}
    if tachlis_cols.get('user_id', {}).get('nullable') is False:
        with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
            batch_op.alter_column('user_id', existing_type=sa.String(length=50), nullable=True)

    # Fresh inspector for the unique indexes on the new token columns --
    # reusing the one from above can return a stale pre-add_column
    # snapshot within the same transaction (confirmed live in an earlier
    # migration this session).
    inspector = sa.inspect(bind)
    for table in GUEST_FIELD_TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        ix_name = f'ix_{table}_guest_manage_token'
        if ix_name not in existing_indexes:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.create_index(batch_op.f(ix_name), ['guest_manage_token'], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in GUEST_FIELD_TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        ix_name = f'ix_{table}_guest_manage_token'
        with op.batch_alter_table(table, schema=None) as batch_op:
            if ix_name in existing_indexes:
                batch_op.drop_index(batch_op.f(ix_name))

    tachlis_cols = {c['name']: c for c in inspector.get_columns('tachlis_post')}
    if tachlis_cols.get('user_id', {}).get('nullable') is True:
        with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
            batch_op.alter_column('user_id', existing_type=sa.String(length=50), nullable=False)

    for table in GUEST_FIELD_TABLES:
        columns = {c['name'] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'guest_manage_token' in columns:
                batch_op.drop_column('guest_manage_token')
            if 'guest_phone' in columns:
                batch_op.drop_column('guest_phone')
            if 'guest_email' in columns:
                batch_op.drop_column('guest_email')
