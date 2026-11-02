"""add guest_submission_throttle table

Revision ID: e8b4d1a9c3f6
Revises: c5f1a7e3b9d2
Create Date: 2026-11-02 00:00:00.000000

Shared infrastructure for the cross-site "post without an account" feature
-- a per-IP, per-day counter capping anonymous guest submissions across
every content type (jobs, listings, businesses, comments, ...). DB-backed
rather than Flask-Limiter's default in-memory store, since this app runs
serverless with pool_size=1/cold starts per invocation (see
backend/guest/modals/guest_throttle.py's own docstring). Brand-new table,
nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table/indexes already exist or
not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8b4d1a9c3f6'
down_revision = 'c5f1a7e3b9d2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'guest_submission_throttle' not in inspector.get_table_names():
        op.create_table(
            'guest_submission_throttle',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('identity', sa.String(length=64), nullable=False),
            sa.Column('usage_date', sa.Date(), nullable=False),
            sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('identity', 'usage_date', name='uq_guest_submission_throttle_identity_date'),
        )

    # Fresh inspector -- reusing the one from above can return a stale,
    # pre-create_table snapshot of table existence within the same
    # transaction (confirmed live in an earlier migration this session).
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if 'guest_submission_throttle' in existing_tables:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('guest_submission_throttle')}
        with op.batch_alter_table('guest_submission_throttle', schema=None) as batch_op:
            if 'ix_guest_submission_throttle_identity' not in existing_indexes:
                batch_op.create_index(batch_op.f('ix_guest_submission_throttle_identity'), ['identity'], unique=False)
            if 'ix_guest_submission_throttle_usage_date' not in existing_indexes:
                batch_op.create_index(batch_op.f('ix_guest_submission_throttle_usage_date'), ['usage_date'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'guest_submission_throttle' in inspector.get_table_names():
        op.drop_table('guest_submission_throttle')
