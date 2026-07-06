"""add notification table

Revision ID: 9f3d1c7a2e5b
Revises: 7a1c9f2e4b6d
Create Date: 2026-07-06 18:00:00.000000

Idempotent for the same reason as 7a1c9f2e4b6d — Flask's db.create_all()
runs on every app start and may create this table before this migration
ever runs.
"""
from alembic import op
import sqlalchemy as sa


revision = '9f3d1c7a2e5b'
down_revision = '7a1c9f2e4b6d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('notification'):
        op.create_table(
            'notification',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=False),
            sa.Column('actor_id', sa.String(length=50), nullable=True),
            sa.Column('type', sa.String(length=30), nullable=False),
            sa.Column('message', sa.String(length=200), nullable=False),
            sa.Column('link', sa.String(length=300), nullable=True),
            sa.Column('is_read', sa.Boolean(), nullable=True),
            sa.Column('pub_date', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['user.public_id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('notification')} \
        if inspector.has_table('notification') else set()
    if 'ix_notification_user_id' not in existing_indexes:
        with op.batch_alter_table('notification', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_notification_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_user_id'))
    op.drop_table('notification')
