"""add user.profile_area_changed_at

Revision ID: 28d750af3f47
Revises: bd52938a5b6c
Create Date: 2026-10-29 00:00:00.000001

Powers the weekly digest's passive "moving to a new area" detection (see
backend/alerts/routes/alert.py's _detected_move_for_user) -- stamped only
when a member's profile_area actually changes to a new non-null value
(backend/user/routes/user.py's update_profile), a single bare timestamp
with no history table, same reasoning as the model's own docstring.
Nullable, purely additive.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the column already exists or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '28d750af3f47'
down_revision = 'bd52938a5b6c'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('user')}

    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'profile_area_changed_at' not in columns:
            batch_op.add_column(sa.Column('profile_area_changed_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('user')}

    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'profile_area_changed_at' in columns:
            batch_op.drop_column('profile_area_changed_at')
