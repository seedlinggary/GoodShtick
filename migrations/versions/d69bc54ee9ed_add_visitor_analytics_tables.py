"""add visitor analytics tables

Revision ID: d69bc54ee9ed
Revises: c12622cade6d
Create Date: 2026-07-13 00:00:00.000000

Hand-written rather than `flask db migrate --autogenerate` output: the new
models (backend/analytics/modals/visitor.py) are intentionally not imported
into application.py for this task (application.py is on the shared
do-not-touch list for this batch of work — another engineer owns it while
this lands), and autogenerate can only diff models that are registered on
the app's SQLAlchemy metadata. Written to match this project's usual
autogenerate output shape/style (see 9f3d1c7a2e5b_add_notification_table.py)
including the idempotent has_table/index guards, since db.create_all() is
NOT used in this codebase but the guards are cheap insurance either way.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd69bc54ee9ed'
down_revision = 'c12622cade6d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('visitor_session'):
        op.create_table(
            'visitor_session',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('anonymous_id', sa.String(length=64), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=True),
            sa.Column('country', sa.String(length=100), nullable=True),
            sa.Column('first_seen', sa.DateTime(), nullable=True),
            sa.Column('last_seen', sa.DateTime(), nullable=True),
            sa.Column('page_view_count', sa.Integer(), nullable=True),
            sa.Column('is_localhost', sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['user.public_id'], ),
            sa.PrimaryKeyConstraint('id'),
        )

    if not inspector.has_table('visitor_event'):
        op.create_table(
            'visitor_event',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('anonymous_id', sa.String(length=64), nullable=False),
            sa.Column('event_type', sa.String(length=30), nullable=False),
            sa.Column('path', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    # Re-inspect so newly created tables above are visible to get_indexes().
    inspector = sa.inspect(bind)

    session_indexes = {ix['name'] for ix in inspector.get_indexes('visitor_session')}
    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        if 'ix_visitor_session_anonymous_id' not in session_indexes:
            batch_op.create_index(batch_op.f('ix_visitor_session_anonymous_id'), ['anonymous_id'], unique=False)
        if 'ix_visitor_session_last_seen' not in session_indexes:
            batch_op.create_index(batch_op.f('ix_visitor_session_last_seen'), ['last_seen'], unique=False)

    event_indexes = {ix['name'] for ix in inspector.get_indexes('visitor_event')}
    with op.batch_alter_table('visitor_event', schema=None) as batch_op:
        if 'ix_visitor_event_anonymous_id' not in event_indexes:
            batch_op.create_index(batch_op.f('ix_visitor_event_anonymous_id'), ['anonymous_id'], unique=False)
        if 'ix_visitor_event_created_at' not in event_indexes:
            batch_op.create_index(batch_op.f('ix_visitor_event_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('visitor_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_visitor_event_created_at'))
        batch_op.drop_index(batch_op.f('ix_visitor_event_anonymous_id'))
    op.drop_table('visitor_event')

    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_visitor_session_last_seen'))
        batch_op.drop_index(batch_op.f('ix_visitor_session_anonymous_id'))
    op.drop_table('visitor_session')
