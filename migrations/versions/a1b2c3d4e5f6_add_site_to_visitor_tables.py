"""add site column to visitor_session and visitor_event

Revision ID: a1b2c3d4e5f6
Revises: 3fe473ea5ab2
Create Date: 2026-09-23 00:00:00.000000

Lets "traffic to just the Business sub-site" be filtered directly instead of
inferred from path (both sites' home routes are literally '/', so path alone
can't tell them apart). See backend/analytics/modals/visitor.py's `site`
column docstring for why this is self-reported by the frontend rather than
derived from the request's Host header.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '3fe473ea5ab2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    session_cols = {c['name'] for c in inspector.get_columns('visitor_session')}
    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        if 'site' not in session_cols:
            batch_op.add_column(sa.Column('site', sa.String(length=20), nullable=True))

    event_cols = {c['name'] for c in inspector.get_columns('visitor_event')}
    with op.batch_alter_table('visitor_event', schema=None) as batch_op:
        if 'site' not in event_cols:
            batch_op.add_column(sa.Column('site', sa.String(length=20), nullable=True))

    inspector = sa.inspect(bind)
    session_indexes = {ix['name'] for ix in inspector.get_indexes('visitor_session')}
    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        if 'ix_visitor_session_site' not in session_indexes:
            batch_op.create_index(batch_op.f('ix_visitor_session_site'), ['site'], unique=False)

    event_indexes = {ix['name'] for ix in inspector.get_indexes('visitor_event')}
    with op.batch_alter_table('visitor_event', schema=None) as batch_op:
        if 'ix_visitor_event_site' not in event_indexes:
            batch_op.create_index(batch_op.f('ix_visitor_event_site'), ['site'], unique=False)


def downgrade():
    with op.batch_alter_table('visitor_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_visitor_event_site'))
        batch_op.drop_column('site')

    with op.batch_alter_table('visitor_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_visitor_session_site'))
        batch_op.drop_column('site')
