"""add login_log table

Revision ID: c3e7a81f9b2d
Revises: a9c485337e48
Create Date: 2026-10-30 00:00:00.000000

Append-only record of every real login attempt -- password login
(application.py's /login) and cross-site SSO handoff (backend/user/routes/
sso.py's /sso/exchange) -- success and failure alike (see
backend/user/modals/login_log.py's log_login). Replaces the previous
situation where no login history existed at all: User.last_login is a
single column that gets overwritten every login, with no history to query.
Brand-new table, nothing existing is touched.

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether the table/indexes already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e7a81f9b2d'
down_revision = 'a9c485337e48'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'login_log' not in inspector.get_table_names():
        op.create_table(
            'login_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=True),
            sa.Column('email_attempted', sa.String(length=255), nullable=True),
            sa.Column('site', sa.String(length=20), nullable=True),
            sa.Column('method', sa.String(length=20), nullable=False),
            sa.Column('success', sa.Boolean(), nullable=False),
            sa.Column('ip_address', sa.String(length=64), nullable=True),
            sa.Column('user_agent', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    existing_fks = set()
    existing_indexes = set()
    if 'login_log' in inspector.get_table_names():
        existing_fks = {fk['name'] for fk in inspector.get_foreign_keys('login_log')}
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('login_log')}

    with op.batch_alter_table('login_log', schema=None) as batch_op:
        if 'fk_login_log_user_id_user' not in existing_fks:
            batch_op.create_foreign_key(
                'fk_login_log_user_id_user', 'user', ['user_id'], ['public_id'],
            )
        if 'ix_login_log_user_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_login_log_user_id'), ['user_id'], unique=False)
        if 'ix_login_log_site' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_login_log_site'), ['site'], unique=False)
        if 'ix_login_log_created_at' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_login_log_created_at'), ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'login_log' in inspector.get_table_names():
        op.drop_table('login_log')
