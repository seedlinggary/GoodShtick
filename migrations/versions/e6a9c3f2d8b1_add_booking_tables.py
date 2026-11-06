"""add service_type, availability_rule, recurrence_rule, and appointment tables

Revision ID: e6a9c3f2d8b1
Revises: d2f8b5c1e9a4
Create Date: 2026-11-05 00:00:04.000000

Phase 5 of the business-owner website builder (see plan file
tender-inventing-teapot.md): calendar-based service booking. Purely
additive -- no existing table or column is touched. recurrence_rule and
appointment both reference each other (appointment.recurrence_id ->
recurrence_rule.id); recurrence_rule is created first so that FK can be
added, matching the one-directional dependency actually needed (an
appointment points at the rule that generated it, not the reverse).

Guarded with inspector checks the same way prior migrations in this chain
are, so this is safe to run whether these tables already exist or not.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6a9c3f2d8b1'
down_revision = 'd2f8b5c1e9a4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'service_type' not in existing_tables:
        op.create_table(
            'service_type',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='30'),
            sa.Column('price_cents', sa.Integer(), nullable=True),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'availability_rule' not in existing_tables:
        op.create_table(
            'availability_rule',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('service_type_id', sa.Integer(), sa.ForeignKey('service_type.id'), nullable=True),
            sa.Column('weekday', sa.Integer(), nullable=False),
            sa.Column('start_time', sa.Time(), nullable=False),
            sa.Column('end_time', sa.Time(), nullable=False),
            sa.Column('slot_interval_minutes', sa.Integer(), nullable=False, server_default='30'),
        )

    if 'recurrence_rule' not in existing_tables:
        op.create_table(
            'recurrence_rule',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('service_type_id', sa.Integer(), sa.ForeignKey('service_type.id'), nullable=False),
            sa.Column('customer_user_id', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('guest_email', sa.String(length=150), nullable=True),
            sa.Column('guest_phone', sa.String(length=40), nullable=True),
            sa.Column('recurrence_type', sa.String(length=16), nullable=False),
            sa.Column('interval', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('start_date', sa.Date(), nullable=False),
            sa.Column('end_date', sa.Date(), nullable=True),
            sa.Column('occurrence_count', sa.Integer(), nullable=True),
            sa.Column('start_hour', sa.Integer(), nullable=False),
            sa.Column('start_minute', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'appointment' not in existing_tables:
        op.create_table(
            'appointment',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
            sa.Column('service_type_id', sa.Integer(), sa.ForeignKey('service_type.id'), nullable=False),
            sa.Column('recurrence_id', sa.Integer(), sa.ForeignKey('recurrence_rule.id'), nullable=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id'), nullable=True),
            sa.Column('customer_user_id', sa.String(length=50), sa.ForeignKey('user.public_id'), nullable=True),
            sa.Column('guest_email', sa.String(length=150), nullable=True),
            sa.Column('guest_phone', sa.String(length=40), nullable=True),
            sa.Column('guest_manage_token', sa.String(length=64), nullable=True),
            sa.Column('start_at', sa.DateTime(), nullable=False),
            sa.Column('end_at', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='scheduled'),
            sa.Column('override_price_cents', sa.Integer(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('service_type')}
    with op.batch_alter_table('service_type', schema=None) as batch_op:
        if 'ix_service_type_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_service_type_business_id'), ['business_id'], unique=False)
        if 'ix_service_type_active' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_service_type_active'), ['active'], unique=False)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('availability_rule')}
    with op.batch_alter_table('availability_rule', schema=None) as batch_op:
        if 'ix_availability_rule_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_availability_rule_business_id'), ['business_id'], unique=False)
        if 'ix_availability_rule_service_type_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_availability_rule_service_type_id'), ['service_type_id'], unique=False)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('recurrence_rule')}
    with op.batch_alter_table('recurrence_rule', schema=None) as batch_op:
        if 'ix_recurrence_rule_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_recurrence_rule_business_id'), ['business_id'], unique=False)
        if 'ix_recurrence_rule_service_type_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_recurrence_rule_service_type_id'), ['service_type_id'], unique=False)
        if 'ix_recurrence_rule_active' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_recurrence_rule_active'), ['active'], unique=False)

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('appointment')}
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('appointment')}
    with op.batch_alter_table('appointment', schema=None) as batch_op:
        if 'ix_appointment_business_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_appointment_business_id'), ['business_id'], unique=False)
        if 'ix_appointment_service_type_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_appointment_service_type_id'), ['service_type_id'], unique=False)
        if 'ix_appointment_recurrence_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_appointment_recurrence_id'), ['recurrence_id'], unique=False)
        if 'ix_appointment_customer_user_id' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_appointment_customer_user_id'), ['customer_user_id'], unique=False)
        if 'ix_appointment_start_at' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_appointment_start_at'), ['start_at'], unique=False)
        if 'ix_appointment_status' not in existing_indexes:
            batch_op.create_index(batch_op.f('ix_appointment_status'), ['status'], unique=False)
        if 'uq_appointment_guest_manage_token' not in existing_uniques:
            batch_op.create_unique_constraint('uq_appointment_guest_manage_token', ['guest_manage_token'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if 'appointment' in existing_tables:
        op.drop_table('appointment')
    if 'recurrence_rule' in existing_tables:
        op.drop_table('recurrence_rule')
    if 'availability_rule' in existing_tables:
        op.drop_table('availability_rule')
    if 'service_type' in existing_tables:
        op.drop_table('service_type')
