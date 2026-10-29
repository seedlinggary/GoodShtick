"""add tachlis_post.business_id

Revision ID: bd52938a5b6c
Revises: d8a63f17c9e2
Create Date: 2026-10-29 00:00:00.000000

Powers the Business <-> Job Board hiring loop: a claimed business can post
a job directly to the Job Board (see backend/tachlis/routes/tachlis_post.py's
create_post, backend/business/routes/business_owner_tools.py's new Hiring
tab). Nullable -- most posts stay personal, not business-sourced; this is
purely additive, nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the column/index already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd52938a5b6c'
down_revision = 'd8a63f17c9e2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('tachlis_post')}
    indexes = {ix['name'] for ix in inspector.get_indexes('tachlis_post')}

    with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
        if 'business_id' not in columns:
            batch_op.add_column(sa.Column('business_id', sa.Integer(), nullable=True))
        if 'ix_tachlis_post_business_id' not in indexes:
            batch_op.create_index(batch_op.f('ix_tachlis_post_business_id'), ['business_id'], unique=False)
        if 'business_id' not in columns:
            # Only add the FK when the column itself was just added -- if it
            # already existed from a previous partial run, assume the FK
            # does too rather than risk a duplicate-constraint error.
            batch_op.create_foreign_key(
                'fk_tachlis_post_business_id_business', 'business', ['business_id'], ['id'],
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('tachlis_post')}
    indexes = {ix['name'] for ix in inspector.get_indexes('tachlis_post')}

    with op.batch_alter_table('tachlis_post', schema=None) as batch_op:
        if 'ix_tachlis_post_business_id' in indexes:
            batch_op.drop_index(batch_op.f('ix_tachlis_post_business_id'))
        if 'business_id' in columns:
            batch_op.drop_constraint('fk_tachlis_post_business_id_business', type_='foreignkey')
            batch_op.drop_column('business_id')
