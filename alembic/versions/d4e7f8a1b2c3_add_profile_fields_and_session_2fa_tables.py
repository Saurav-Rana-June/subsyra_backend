"""add profile fields, sessions, 2fa recovery codes, and email verification tables

Revision ID: d4e7f8a1b2c3
Revises: 9ca37466bc00
Create Date: 2026-11-11 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e7f8a1b2c3'
down_revision: Union[str, Sequence[str], None] = '9ca37466bc00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users_table', sa.Column('first_name', sa.String(), nullable=True))
    op.add_column('users_table', sa.Column('last_name', sa.String(), nullable=True))
    op.add_column('users_table', sa.Column('display_name', sa.String(), nullable=True))
    op.add_column('users_table', sa.Column('job_title', sa.String(), nullable=True))
    op.add_column('users_table', sa.Column('country_code', sa.String(length=10), server_default='+91', nullable=False))
    op.alter_column('users_table', 'mobile_number', type_=sa.String(length=20), existing_type=sa.String(length=10), existing_nullable=False)
    op.add_column('users_table', sa.Column('avatar_tone_index', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users_table', sa.Column('is_email_verified', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('users_table', sa.Column('pending_email', sa.String(), nullable=True))
    op.add_column('users_table', sa.Column('two_factor_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users_table', sa.Column('two_factor_secret', sa.String(), nullable=True))
    op.add_column('users_table', sa.Column('token_version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('users_table', sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users_table', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('users_table', sa.Column('pref_language', sa.String(length=16), server_default='en-US', nullable=False))
    op.add_column('users_table', sa.Column('pref_timezone', sa.String(length=32), server_default='IST', nullable=False))
    op.add_column('users_table', sa.Column('pref_date_format', sa.String(length=20), server_default='DD.MM.YYYY', nullable=False))
    op.add_column('users_table', sa.Column('pref_theme', sa.String(length=16), server_default='system', nullable=False))
    op.add_column('users_table', sa.Column('notif_security_alerts', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('users_table', sa.Column('notif_billing_summaries', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('users_table', sa.Column('notif_payment_failures', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('users_table', sa.Column('notif_product_updates', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users_table', sa.Column('notif_billing_frequency', sa.String(length=16), server_default='weekly', nullable=False))

    op.create_table(
        'user_sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('device', sa.String(length=160), nullable=False),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('location', sa.String(length=160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_active_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users_table.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_sessions_jti'), 'user_sessions', ['jti'], unique=True)
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)

    op.create_table(
        'user_recovery_codes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code_hash', sa.String(length=128), nullable=False),
        sa.Column('code_hint', sa.String(length=32), nullable=False),
        sa.Column('is_used', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users_table.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_recovery_codes_user_id'), 'user_recovery_codes', ['user_id'], unique=False)

    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('token', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users_table.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_verification_tokens_token'), 'email_verification_tokens', ['token'], unique=True)
    op.create_index(op.f('ix_email_verification_tokens_user_id'), 'email_verification_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_email_verification_tokens_user_id'), table_name='email_verification_tokens')
    op.drop_index(op.f('ix_email_verification_tokens_token'), table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')

    op.drop_index(op.f('ix_user_recovery_codes_user_id'), table_name='user_recovery_codes')
    op.drop_table('user_recovery_codes')

    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_jti'), table_name='user_sessions')
    op.drop_table('user_sessions')

    for col in [
        'notif_billing_frequency',
        'notif_product_updates',
        'notif_payment_failures',
        'notif_billing_summaries',
        'notif_security_alerts',
        'pref_theme',
        'pref_date_format',
        'pref_timezone',
        'pref_language',
        'deleted_at',
        'is_deleted',
        'token_version',
        'two_factor_secret',
        'two_factor_enabled',
        'pending_email',
        'is_email_verified',
        'avatar_tone_index',
        'country_code',
        'job_title',
        'display_name',
        'last_name',
        'first_name',
    ]:
        op.drop_column('users_table', col)
    op.alter_column('users_table', 'mobile_number', type_=sa.String(length=10), existing_type=sa.String(length=20), existing_nullable=False)

