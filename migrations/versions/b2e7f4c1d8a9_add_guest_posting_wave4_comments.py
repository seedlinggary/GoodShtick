"""guest posting wave 4 -- comments (shtick, hock, business)

Revision ID: b2e7f4c1d8a9
Revises: a1d6e9c4b7f2
Create Date: 2026-11-02 00:00:00.000003

Adds guest_email/guest_phone/guest_manage_token (same shape as earlier
waves) to Comment (Shtick)/HockComment/BusinessComment, relaxes each
table's user_id from NOT NULL to nullable (a guest comment has no user),
and relaxes approved_to_publish from NOT NULL to nullable so a guest
comment can land in the same None = "pending" state the other domains
use -- every one of these three tables' GET routes already filters
non-admin viewers to `approved_to_publish == True`, so None is already
correctly excluded with zero route-level filter changes needed. No
backfill required: every existing row already has a real True/False
value, never NULL.

Guarded with inspector checks the same way prior migrations in this
chain are, so this is safe to run whether the columns already exist or
not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2e7f4c1d8a9'
down_revision = 'a1d6e9c4b7f2'
branch_labels = None
depends_on = None

TABLES = ('comment', 'hock_comment', 'business_comment')


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in TABLES:
        columns = {c['name']: c for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if 'guest_email' not in columns:
                batch_op.add_column(sa.Column('guest_email', sa.String(length=150), nullable=True))
            if 'guest_phone' not in columns:
                batch_op.add_column(sa.Column('guest_phone', sa.String(length=40), nullable=True))
            if 'guest_manage_token' not in columns:
                batch_op.add_column(sa.Column('guest_manage_token', sa.String(length=64), nullable=True))
            if columns.get('user_id', {}).get('nullable') is False:
                batch_op.alter_column('user_id', existing_type=sa.String(length=50), nullable=True)
            if columns.get('approved_to_publish', {}).get('nullable') is False:
                batch_op.alter_column('approved_to_publish', existing_type=sa.Boolean(), nullable=True)

    # Fresh inspector -- reusing the one from above can return a stale
    # pre-add_column snapshot within the same transaction (confirmed live
    # in earlier migrations this session).
    inspector = sa.inspect(bind)
    for table in TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        ix_name = f'ix_{table}_guest_manage_token'
        if ix_name not in existing_indexes:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.create_index(batch_op.f(ix_name), ['guest_manage_token'], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in TABLES:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes(table)}
        ix_name = f'ix_{table}_guest_manage_token'
        with op.batch_alter_table(table, schema=None) as batch_op:
            if ix_name in existing_indexes:
                batch_op.drop_index(batch_op.f(ix_name))

    for table in TABLES:
        columns = {c['name']: c for c in inspector.get_columns(table)}
        with op.batch_alter_table(table, schema=None) as batch_op:
            if columns.get('approved_to_publish', {}).get('nullable') is True:
                batch_op.alter_column('approved_to_publish', existing_type=sa.Boolean(), nullable=False)
            if columns.get('user_id', {}).get('nullable') is True:
                batch_op.alter_column('user_id', existing_type=sa.String(length=50), nullable=False)
            if 'guest_manage_token' in columns:
                batch_op.drop_column('guest_manage_token')
            if 'guest_phone' in columns:
                batch_op.drop_column('guest_phone')
            if 'guest_email' in columns:
                batch_op.drop_column('guest_email')
