"""add scraped_job table

Dedup record for jobs pulled from external sources (Arbeitnow, RemoteOK,
Jobicy, AllJobs) -- see backend/tachlis/routes/job_scraper.py. Purely
additive; inspector-guarded so it's safe to re-run.

Revision ID: 8b0f718cf037
Revises: dda7cd11aabc
Create Date: 2026-11-24 19:27:05.983804

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8b0f718cf037'
down_revision = 'dda7cd11aabc'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'scraped_job' in inspector.get_table_names():
        return
    op.create_table('scraped_job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=True),
        sa.Column('tachlis_post_id', sa.Integer(), nullable=True),
        sa.Column('scraped_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tachlis_post_id'], ['tachlis_post.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'url', name='uq_scraped_job_source_url')
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'scraped_job' in inspector.get_table_names():
        op.drop_table('scraped_job')
