"""add giveaway campaign tables

Revision ID: dda7cd11aabc
Revises: e3d1f37410b8
Create Date: 2026-11-19 13:44:58.728834

Nine brand-new tables for backend/giveaways/ (GiveawayCampaign,
GiveawayEntryAction, GiveawayParticipant, GiveawayParticipation,
GiveawayEntry, GiveawayReferralClick, GiveawayDrawSnapshot, GiveawayDraw,
GiveawayEntryThrottle -- see backend/giveaways/modals/giveaway.py). Purely
additive, nothing existing is touched. Trimmed from autogenerate's raw
output, which also picked up unrelated index/constraint cosmetic drift on
alert/appointment/community_data_cache/marketplace_listing/order (from
other recent model changes, not part of this change) and a real but
unrelated pending drop of news_article.category -- none of that belongs
in this migration, so only the nine giveaway_* table creations below are
kept, same as the most recent prior migration's own plain create_table
style (brand-new tables don't need the inspector guards that an ALTER on
an existing table does).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dda7cd11aabc'
down_revision = 'e3d1f37410b8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('giveaway_entry_throttle',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('identity', sa.String(length=64), nullable=False),
    sa.Column('usage_date', sa.Date(), nullable=False),
    sa.Column('count', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('identity', 'usage_date', name='uq_giveaway_entry_throttle_identity_date')
    )
    with op.batch_alter_table('giveaway_entry_throttle', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_entry_throttle_identity'), ['identity'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_entry_throttle_usage_date'), ['usage_date'], unique=False)

    op.create_table('giveaway_participant',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=True),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('user_id', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.public_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('giveaway_participant', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_participant_email'), ['email'], unique=True)

    op.create_table('giveaway_campaign',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('campaign_type', sa.String(length=30), server_default='giveaway', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('sites', sa.JSON(), nullable=True),
    sa.Column('starts_at', sa.DateTime(), nullable=True),
    sa.Column('ends_at', sa.DateTime(), nullable=True),
    sa.Column('prize_details', sa.Text(), nullable=True),
    sa.Column('terms_text', sa.Text(), nullable=True),
    sa.Column('privacy_note', sa.Text(), nullable=True),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('entry_rules', sa.JSON(), nullable=True),
    sa.Column('marketing_campaign_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['user.public_id'], ),
    sa.ForeignKeyConstraint(['marketing_campaign_id'], ['marketing_campaign.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('giveaway_campaign', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_campaign_slug'), ['slug'], unique=True)

    op.create_table('giveaway_draw_snapshot',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('eligible_count', sa.Integer(), nullable=False),
    sa.Column('pool_json', sa.JSON(), nullable=False),
    sa.Column('rules_applied', sa.JSON(), nullable=True),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['giveaway_campaign.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['user.public_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('giveaway_draw_snapshot', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_draw_snapshot_campaign_id'), ['campaign_id'], unique=False)

    op.create_table('giveaway_entry_action',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('action_key', sa.String(length=60), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('action_url', sa.String(length=500), nullable=True),
    sa.Column('entry_quantity', sa.Integer(), server_default='1', nullable=False),
    sa.Column('is_required', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('verification_method', sa.String(length=20), server_default='self_certify', nullable=False),
    sa.Column('max_completions', sa.Integer(), server_default='1', nullable=True),
    sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['giveaway_campaign.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'action_key', name='uq_giveaway_entry_action_campaign_key')
    )
    with op.batch_alter_table('giveaway_entry_action', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_entry_action_campaign_id'), ['campaign_id'], unique=False)

    op.create_table('giveaway_participation',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('participant_id', sa.Integer(), nullable=False),
    sa.Column('referral_code', sa.String(length=16), nullable=False),
    sa.Column('referrer_participation_id', sa.Integer(), nullable=True),
    sa.Column('first_touch', sa.JSON(), nullable=True),
    sa.Column('last_touch', sa.JSON(), nullable=True),
    sa.Column('consent_marketing', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('consent_at', sa.DateTime(), nullable=True),
    sa.Column('consent_source', sa.String(length=60), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='pending_verification', nullable=False),
    sa.Column('fraud_flags', sa.JSON(), nullable=True),
    sa.Column('verify_token', sa.String(length=64), nullable=True),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['giveaway_campaign.id'], ),
    sa.ForeignKeyConstraint(['participant_id'], ['giveaway_participant.id'], ),
    sa.ForeignKeyConstraint(['referrer_participation_id'], ['giveaway_participation.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'participant_id', name='uq_giveaway_participation_campaign_participant')
    )
    with op.batch_alter_table('giveaway_participation', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_participation_campaign_id'), ['campaign_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_participation_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_participation_participant_id'), ['participant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_participation_referral_code'), ['referral_code'], unique=True)
        batch_op.create_index(batch_op.f('ix_giveaway_participation_verify_token'), ['verify_token'], unique=True)

    op.create_table('giveaway_draw',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('drawn_at', sa.DateTime(), nullable=True),
    sa.Column('algorithm', sa.String(length=60), server_default='secrets_weighted_random', nullable=False),
    sa.Column('winner_participation_id', sa.Integer(), nullable=False),
    sa.Column('is_backup', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('backup_rank', sa.Integer(), nullable=True),
    sa.Column('drawn_by', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['giveaway_campaign.id'], ),
    sa.ForeignKeyConstraint(['drawn_by'], ['user.public_id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['giveaway_draw_snapshot.id'], ),
    sa.ForeignKeyConstraint(['winner_participation_id'], ['giveaway_participation.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('giveaway_draw', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_draw_campaign_id'), ['campaign_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_draw_snapshot_id'), ['snapshot_id'], unique=False)

    op.create_table('giveaway_entry',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('participation_id', sa.Integer(), nullable=False),
    sa.Column('action_key', sa.String(length=60), nullable=False),
    sa.Column('related_participation_id', sa.Integer(), nullable=False),
    sa.Column('entry_quantity', sa.Integer(), server_default='1', nullable=False),
    sa.Column('verification_status', sa.String(length=20), server_default='verified', nullable=False),
    sa.Column('verification_method', sa.String(length=20), nullable=True),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('entry_metadata', sa.JSON(), nullable=True),
    sa.Column('invalidated', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('invalidated_reason', sa.Text(), nullable=True),
    sa.Column('invalidated_by', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['invalidated_by'], ['user.public_id'], ),
    sa.ForeignKeyConstraint(['participation_id'], ['giveaway_participation.id'], ),
    sa.ForeignKeyConstraint(['related_participation_id'], ['giveaway_participation.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('participation_id', 'action_key', 'related_participation_id', name='uq_giveaway_entry_participation_action_related')
    )
    with op.batch_alter_table('giveaway_entry', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_entry_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_entry_participation_id'), ['participation_id'], unique=False)

    op.create_table('giveaway_referral_click',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('participation_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('referrer', sa.String(length=500), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('country', sa.String(length=100), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['participation_id'], ['giveaway_participation.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('giveaway_referral_click', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_giveaway_referral_click_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_giveaway_referral_click_participation_id'), ['participation_id'], unique=False)


def downgrade():
    with op.batch_alter_table('giveaway_referral_click', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_referral_click_participation_id'))
        batch_op.drop_index(batch_op.f('ix_giveaway_referral_click_created_at'))

    op.drop_table('giveaway_referral_click')
    with op.batch_alter_table('giveaway_entry', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_entry_participation_id'))
        batch_op.drop_index(batch_op.f('ix_giveaway_entry_created_at'))

    op.drop_table('giveaway_entry')
    with op.batch_alter_table('giveaway_draw', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_draw_snapshot_id'))
        batch_op.drop_index(batch_op.f('ix_giveaway_draw_campaign_id'))

    op.drop_table('giveaway_draw')
    with op.batch_alter_table('giveaway_participation', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_participation_verify_token'))
        batch_op.drop_index(batch_op.f('ix_giveaway_participation_referral_code'))
        batch_op.drop_index(batch_op.f('ix_giveaway_participation_participant_id'))
        batch_op.drop_index(batch_op.f('ix_giveaway_participation_created_at'))
        batch_op.drop_index(batch_op.f('ix_giveaway_participation_campaign_id'))

    op.drop_table('giveaway_participation')
    with op.batch_alter_table('giveaway_entry_action', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_entry_action_campaign_id'))

    op.drop_table('giveaway_entry_action')
    with op.batch_alter_table('giveaway_draw_snapshot', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_draw_snapshot_campaign_id'))

    op.drop_table('giveaway_draw_snapshot')
    with op.batch_alter_table('giveaway_campaign', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_campaign_slug'))

    op.drop_table('giveaway_campaign')
    with op.batch_alter_table('giveaway_participant', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_participant_email'))

    op.drop_table('giveaway_participant')
    with op.batch_alter_table('giveaway_entry_throttle', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_giveaway_entry_throttle_usage_date'))
        batch_op.drop_index(batch_op.f('ix_giveaway_entry_throttle_identity'))

    op.drop_table('giveaway_entry_throttle')
