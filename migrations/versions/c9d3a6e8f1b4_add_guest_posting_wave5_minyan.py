"""guest posting wave 5 -- minyan times

Revision ID: c9d3a6e8f1b4
Revises: b2e7f4c1d8a9
Create Date: 2026-11-02 00:00:00.000004

Minyan had no moderation gate of any kind before this -- it's created only
via the shul's claimed/created owner (see routes/minyan.py's _can_manage),
so list_minyanim/search_minyanim have always shown every row unconditionally.
This adds a brand new three-state approved_to_publish gate (None = pending
guest submission awaiting admin review, True = live, False = rejected),
backfilled to True for every existing row so nothing already public goes
dark, plus the same guest_email/guest_phone/guest_manage_token shape every
other wave uses. The existing owner-only add_minyan path is unaffected --
it keeps setting approved_to_publish=True immediately, same as it
implicitly always has.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d3a6e8f1b4'
down_revision = 'b2e7f4c1d8a9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('minyan')}

    with op.batch_alter_table('minyan', schema=None) as batch_op:
        if 'guest_email' not in columns:
            batch_op.add_column(sa.Column('guest_email', sa.String(length=150), nullable=True))
        if 'guest_phone' not in columns:
            batch_op.add_column(sa.Column('guest_phone', sa.String(length=40), nullable=True))
        if 'guest_manage_token' not in columns:
            batch_op.add_column(sa.Column('guest_manage_token', sa.String(length=64), nullable=True))
        if 'approved_to_publish' not in columns:
            batch_op.add_column(sa.Column('approved_to_publish', sa.Boolean(), nullable=True))

    if 'approved_to_publish' not in columns:
        op.execute('UPDATE minyan SET approved_to_publish = TRUE WHERE approved_to_publish IS NULL')

    # Fresh inspector -- reusing the one from above can return a stale
    # pre-add_column snapshot within the same transaction (confirmed live
    # in earlier migrations this session).
    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('minyan')}
    with op.batch_alter_table('minyan', schema=None) as batch_op:
        if 'ix_minyan_guest_manage_token' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_minyan_guest_manage_token'), ['guest_manage_token'], unique=True)
        if 'ix_minyan_approved_to_publish' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_minyan_approved_to_publish'), ['approved_to_publish'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('minyan')}
    with op.batch_alter_table('minyan', schema=None) as batch_op:
        if 'ix_minyan_approved_to_publish' in existing_indexes:
            batch_op.drop_index(batch_op.f('ix_minyan_approved_to_publish'))
        if 'ix_minyan_guest_manage_token' in existing_indexes:
            batch_op.drop_index(batch_op.f('ix_minyan_guest_manage_token'))

    columns = {c['name'] for c in inspector.get_columns('minyan')}
    with op.batch_alter_table('minyan', schema=None) as batch_op:
        if 'approved_to_publish' in columns:
            batch_op.drop_column('approved_to_publish')
        if 'guest_manage_token' in columns:
            batch_op.drop_column('guest_manage_token')
        if 'guest_phone' in columns:
            batch_op.drop_column('guest_phone')
        if 'guest_email' in columns:
            batch_op.drop_column('guest_email')
