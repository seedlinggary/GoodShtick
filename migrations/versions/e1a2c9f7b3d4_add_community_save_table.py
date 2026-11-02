"""add community_save table

Revision ID: e1a2c9f7b3d4
Revises: c3e7a81f9b2d
Create Date: 2026-10-31 00:00:00.000000

A member's own "save this community" bookmark -- lets someone keep a
shortlist of communities they're considering while comparing a few before a
move (see backend/business/modals/community.py's CommunitySave,
backend/business/routes/community.py's save_community/unsave_community/
list_saved_communities). Brand-new table, nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table/indexes already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1a2c9f7b3d4'
down_revision = 'c3e7a81f9b2d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'community_save' not in inspector.get_table_names():
        op.create_table(
            'community_save',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=False),
            sa.Column('community_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'community_id', name='uq_community_save_user_community'),
        )

    existing_fks = set()
    existing_indexes = set()
    if 'community_save' in inspector.get_table_names():
        existing_fks = {fk['name'] for fk in inspector.get_foreign_keys('community_save')}
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('community_save')}

    with op.batch_alter_table('community_save', schema=None) as batch_op:
        if 'fk_community_save_user_id_user' not in existing_fks:
            batch_op.create_foreign_key(
                'fk_community_save_user_id_user', 'user', ['user_id'], ['public_id'],
            )
        if 'fk_community_save_community_id_community' not in existing_fks:
            batch_op.create_foreign_key(
                'fk_community_save_community_id_community', 'community', ['community_id'], ['id'],
            )
        if 'ix_community_save_user_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_community_save_user_id'), ['user_id'], unique=False)
        if 'ix_community_save_community_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_community_save_community_id'), ['community_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'community_save' in inspector.get_table_names():
        op.drop_table('community_save')
