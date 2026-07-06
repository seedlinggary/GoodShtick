"""add ad platform and user targeting fields

Revision ID: 7a1c9f2e4b6d
Revises: 3fab98ab4d4e
Create Date: 2026-07-06 12:00:00.000000

Written to be idempotent: on this project, Flask's `db.create_all()` runs on
every app start and will auto-create brand-new tables (ad/ad_impression/
ad_click) before this migration ever gets a chance to run, if the app code
is deployed/started before `flask db upgrade` is. Guard every operation so
this migration is safe to run whether those tables/columns already exist or
not — needed once already, keep it this way for future fresh databases too.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a1c9f2e4b6d'
down_revision = '3fab98ab4d4e'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_columns = {c['name'] for c in inspector.get_columns('user')}
    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'birthdate' not in user_columns:
            batch_op.add_column(sa.Column('birthdate', sa.Date(), nullable=True))
        if 'gender' not in user_columns:
            batch_op.add_column(sa.Column('gender', sa.String(length=20), nullable=True))
        if 'location_country' not in user_columns:
            batch_op.add_column(sa.Column('location_country', sa.String(length=100), nullable=True))
        if 'location_city' not in user_columns:
            batch_op.add_column(sa.Column('location_city', sa.String(length=100), nullable=True))

    if not inspector.has_table('ad'):
        op.create_table(
            'ad',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('advertiser_name', sa.String(length=120), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('image_name', sa.String(length=200), nullable=True),
            sa.Column('headline', sa.String(length=200), nullable=True),
            sa.Column('body_text', sa.Text(), nullable=True),
            sa.Column('cta_label', sa.String(length=40), nullable=True),
            sa.Column('destination_type', sa.String(length=20), nullable=True),
            sa.Column('destination_value', sa.String(length=500), nullable=False),
            sa.Column('placement', sa.String(length=30), nullable=True),
            sa.Column('target_age_min', sa.Integer(), nullable=True),
            sa.Column('target_age_max', sa.Integer(), nullable=True),
            sa.Column('target_gender', sa.String(length=20), nullable=True),
            sa.Column('target_countries', sa.String(length=500), nullable=True),
            sa.Column('start_date', sa.DateTime(), nullable=True),
            sa.Column('end_date', sa.DateTime(), nullable=True),
            sa.Column('weight', sa.Integer(), nullable=True),
            sa.Column('impression_count', sa.Integer(), nullable=True),
            sa.Column('click_count', sa.Integer(), nullable=True),
            sa.Column('created_by', sa.String(length=50), nullable=True),
            sa.Column('pub_date', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    if not inspector.has_table('ad_impression'):
        op.create_table(
            'ad_impression',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('ad_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=True),
            sa.Column('placement', sa.String(length=30), nullable=True),
            sa.Column('country', sa.String(length=100), nullable=True),
            sa.Column('viewed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['ad_id'], ['ad.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('ad_impression')} \
        if inspector.has_table('ad_impression') else set()
    if 'ix_ad_impression_ad_id' not in existing_indexes:
        with op.batch_alter_table('ad_impression', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_ad_impression_ad_id'), ['ad_id'], unique=False)

    if not inspector.has_table('ad_click'):
        op.create_table(
            'ad_click',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('ad_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=50), nullable=True),
            sa.Column('country', sa.String(length=100), nullable=True),
            sa.Column('clicked_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['ad_id'], ['ad.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('ad_click')} \
        if inspector.has_table('ad_click') else set()
    if 'ix_ad_click_ad_id' not in existing_indexes:
        with op.batch_alter_table('ad_click', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_ad_click_ad_id'), ['ad_id'], unique=False)


def downgrade():
    with op.batch_alter_table('ad_click', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ad_click_ad_id'))
    op.drop_table('ad_click')

    with op.batch_alter_table('ad_impression', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ad_impression_ad_id'))
    op.drop_table('ad_impression')

    op.drop_table('ad')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('location_city')
        batch_op.drop_column('location_country')
        batch_op.drop_column('gender')
        batch_op.drop_column('birthdate')
