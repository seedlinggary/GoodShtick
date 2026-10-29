"""add business_follow.unsubscribe_token

Revision ID: c4f91a7e2b86
Revises: 051a5146d1d5
Create Date: 2026-10-29 00:00:00.000000

Powers the one-click, no-login "unfollow" link in the new deal-alert email
sent from backend/business/routes/business_post.py's
_notify_followers_of_new_deal() -- same pattern as Alert.unsubscribe_token /
User.weekly_digest_token. Nullable: existing BusinessFollow rows get one
lazily backfilled the first time they'd actually need it, same lazy-backfill
convention as EstatesListing.still_available_token.

Guarded with inspector checks the same way b2e4f8a1c9d3/7a1c9f2e4b6d are, so
this is safe to run whether the column/index already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f91a7e2b86'
down_revision = '051a5146d1d5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    follow_columns = {c['name'] for c in inspector.get_columns('business_follow')}
    follow_indexes = {ix['name'] for ix in inspector.get_indexes('business_follow')}

    with op.batch_alter_table('business_follow', schema=None) as batch_op:
        if 'unsubscribe_token' not in follow_columns:
            batch_op.add_column(sa.Column('unsubscribe_token', sa.String(length=64), nullable=True))
        if 'ix_business_follow_unsubscribe_token' not in follow_indexes:
            batch_op.create_index(
                batch_op.f('ix_business_follow_unsubscribe_token'),
                ['unsubscribe_token'], unique=True,
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    follow_columns = {c['name'] for c in inspector.get_columns('business_follow')}
    follow_indexes = {ix['name'] for ix in inspector.get_indexes('business_follow')}

    with op.batch_alter_table('business_follow', schema=None) as batch_op:
        if 'ix_business_follow_unsubscribe_token' in follow_indexes:
            batch_op.drop_index(batch_op.f('ix_business_follow_unsubscribe_token'))
        if 'unsubscribe_token' in follow_columns:
            batch_op.drop_column('unsubscribe_token')
