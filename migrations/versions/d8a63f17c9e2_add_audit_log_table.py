"""add audit_log table

Revision ID: d8a63f17c9e2
Revises: c4f91a7e2b86
Create Date: 2026-10-29 00:00:00.000000

Append-only record of who did what, when, for SuperAdmin actions that have
no other undo path -- role changes, ad status changes/deletion, category
deletion, unapproving a post (see backend/user/modals/audit_log.py). Purely
additive: a brand-new table, nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8a63f17c9e2'
down_revision = 'c4f91a7e2b86'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'audit_log' not in inspector.get_table_names():
        op.create_table(
            'audit_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('actor_public_id', sa.String(length=50), nullable=True),
            sa.Column('action', sa.String(length=50), nullable=False),
            sa.Column('target_type', sa.String(length=50), nullable=True),
            sa.Column('target_id', sa.String(length=50), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['actor_public_id'], ['user.public_id']),
            sa.PrimaryKeyConstraint('id'),
        )

    existing_indexes = set()
    if 'audit_log' in inspector.get_table_names():
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('audit_log')}

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        if 'ix_audit_log_actor_public_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_audit_log_actor_public_id'), ['actor_public_id'], unique=False)
        if 'ix_audit_log_action' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_audit_log_action'), ['action'], unique=False)
        if 'ix_audit_log_created_at' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_audit_log_created_at'), ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'audit_log' in inspector.get_table_names():
        op.drop_table('audit_log')
