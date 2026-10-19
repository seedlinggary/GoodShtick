"""add community and minyan tables

Revision ID: f3a7c2b891de
Revises: a1b2c3d4e5f6
Create Date: 2026-10-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a7c2b891de'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('community',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=160), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=False),
        sa.Column('state', sa.String(length=80), nullable=True),
        sa.Column('country', sa.String(length=80), nullable=True),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lng', sa.Float(), nullable=True),
        sa.Column('logo', sa.String(length=300), nullable=True),
        sa.Column('source_url', sa.String(length=500), nullable=True),
        sa.Column('source_name', sa.String(length=150), nullable=True),
        sa.Column('imported', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('pub_date', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.public_id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_community_city'), 'community', ['city'], unique=False)
    op.create_index(op.f('ix_community_lat'), 'community', ['lat'], unique=False)
    op.create_index(op.f('ix_community_lng'), 'community', ['lng'], unique=False)
    op.create_index(op.f('ix_community_imported'), 'community', ['imported'], unique=False)
    op.create_index(op.f('ix_community_pub_date'), 'community', ['pub_date'], unique=False)
    op.create_index(op.f('ix_community_slug'), 'community', ['slug'], unique=True)

    op.create_table('minyan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('tefilah', sa.String(length=20), nullable=False),
        sa.Column('label', sa.String(length=150), nullable=True),
        sa.Column('days', sa.String(length=100), nullable=True),
        sa.Column('season', sa.String(length=60), nullable=True),
        sa.Column('fixed_time', sa.Time(), nullable=True),
        sa.Column('relative_anchor', sa.String(length=20), nullable=True),
        sa.Column('relative_offset_minutes', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.Column('source_name', sa.String(length=200), nullable=False),
        sa.Column('source_url', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('pub_date', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['business.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['user.public_id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_minyan_business_id'), 'minyan', ['business_id'], unique=False)
    op.create_index(op.f('ix_minyan_pub_date'), 'minyan', ['pub_date'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_minyan_pub_date'), table_name='minyan')
    op.drop_index(op.f('ix_minyan_business_id'), table_name='minyan')
    op.drop_table('minyan')

    op.drop_index(op.f('ix_community_slug'), table_name='community')
    op.drop_index(op.f('ix_community_pub_date'), table_name='community')
    op.drop_index(op.f('ix_community_imported'), table_name='community')
    op.drop_index(op.f('ix_community_lng'), table_name='community')
    op.drop_index(op.f('ix_community_lat'), table_name='community')
    op.drop_index(op.f('ix_community_city'), table_name='community')
    op.drop_table('community')
