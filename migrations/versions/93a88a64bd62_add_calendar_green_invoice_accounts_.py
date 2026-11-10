"""add calendar/green invoice accounts, favicon, setup wizard, appointment/order columns

Revision ID: 93a88a64bd62
Revises: 4d1fcca29d19
Create Date: 2026-11-10 16:25:57.342651

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '93a88a64bd62'
down_revision = '4d1fcca29d19'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('calendar_account',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), server_default='google', nullable=False),
    sa.Column('calendar_id', sa.String(length=255), server_default='primary', nullable=False),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('refresh_token_enc', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('account_email', sa.String(length=255), nullable=True),
    sa.Column('connected_by', sa.String(length=50), nullable=True),
    sa.Column('connected_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['business_id'], ['business.id'], ),
    sa.ForeignKeyConstraint(['connected_by'], ['user.public_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('calendar_account', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_calendar_account_business_id'), ['business_id'], unique=True)

    op.create_table('green_invoice_account',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('api_key_id', sa.String(length=255), nullable=False),
    sa.Column('api_secret_enc', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('connected_by', sa.String(length=50), nullable=True),
    sa.Column('connected_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['business_id'], ['business.id'], ),
    sa.ForeignKeyConstraint(['connected_by'], ['user.public_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('green_invoice_account', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_green_invoice_account_business_id'), ['business_id'], unique=True)

    with op.batch_alter_table('appointment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('google_event_id', sa.String(length=255), nullable=True))

    with op.batch_alter_table('business_site', schema=None) as batch_op:
        batch_op.add_column(sa.Column('favicon_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('setup_wizard_dismissed', sa.Boolean(), server_default='false', nullable=False))

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('green_invoice_doc_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('green_invoice_pdf_url', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('green_invoice_pdf_url')
        batch_op.drop_column('green_invoice_doc_id')

    with op.batch_alter_table('business_site', schema=None) as batch_op:
        batch_op.drop_column('setup_wizard_dismissed')
        batch_op.drop_column('favicon_url')

    with op.batch_alter_table('appointment', schema=None) as batch_op:
        batch_op.drop_column('google_event_id')

    with op.batch_alter_table('green_invoice_account', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_green_invoice_account_business_id'))
    op.drop_table('green_invoice_account')

    with op.batch_alter_table('calendar_account', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_calendar_account_business_id'))
    op.drop_table('calendar_account')
