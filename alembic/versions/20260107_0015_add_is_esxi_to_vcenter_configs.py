"""Add is_esxi to vcenter_configs

Revision ID: 20260107_0015
Revises: 20251213_0014
Create Date: 2026-01-07 22:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260107_0015'
down_revision = '20251213_0014'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('vcenter_configs', sa.Column('is_esxi', sa.Boolean(), nullable=False, server_default=sa.text('0')))

def downgrade() -> None:
    op.drop_column('vcenter_configs', 'is_esxi')
