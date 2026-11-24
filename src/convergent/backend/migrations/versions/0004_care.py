"""care contact: the family doctor's name, email, phone and booking link, typed in by the parent

Revision ID: 0004_care
Revises: 0003_family
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0004_care'
down_revision = '0003_family'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('app_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('care', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('app_settings', schema=None) as batch_op:
        batch_op.drop_column('care')
