"""Add nonprofit holiday tiers and signup seat_breakdown

Revision ID: 4d1fcca29d19
Revises: c3d9a1f6e274
Create Date: 2026-11-10 08:23:15.047305

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4d1fcca29d19'
down_revision = 'c3d9a1f6e274'
branch_labels = None
depends_on = None


def upgrade():
    # NonprofitHolidayTier -- owner-named price levels per holiday/event
    # (e.g. "Member", "Non-Member", "Child"), replacing the old fixed
    # member_price_cents/non_member_price_cents pair.
    op.create_table('nonprofit_holiday_tier',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('holiday_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['holiday_id'], ['nonprofit_holiday.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('nonprofit_holiday_tier', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nonprofit_holiday_tier_holiday_id'), ['holiday_id'], unique=False)

    # Legacy columns on an existing holiday keep their original value for
    # reference, but a holiday created after this change never sets them --
    # pricing now lives entirely in nonprofit_holiday_tier.
    with op.batch_alter_table('nonprofit_holiday', schema=None) as batch_op:
        batch_op.alter_column('member_price_cents',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.alter_column('non_member_price_cents',
               existing_type=sa.INTEGER(),
               nullable=True)

    # Per-tier seat counts for a new signup -- a signup created before
    # this change has no seat_breakdown and keeps reading from its
    # existing men_seats/women_seats columns (untouched here).
    with op.batch_alter_table('nonprofit_signup', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seat_breakdown', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('nonprofit_signup', schema=None) as batch_op:
        batch_op.drop_column('seat_breakdown')

    with op.batch_alter_table('nonprofit_holiday', schema=None) as batch_op:
        batch_op.alter_column('non_member_price_cents',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.alter_column('member_price_cents',
               existing_type=sa.INTEGER(),
               nullable=False)

    with op.batch_alter_table('nonprofit_holiday_tier', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nonprofit_holiday_tier_holiday_id'))

    op.drop_table('nonprofit_holiday_tier')
