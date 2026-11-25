"""parent app: children, washes, app settings, germ unlocks

Revision ID: 0002_parent_app
Revises: 0001_initial
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0002_parent_app'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('children',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('buddy', sa.String(length=32), nullable=False),
    sa.Column('age_band', sa.String(length=8), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('washes',
    sa.Column('wash_id', sa.String(length=96), nullable=False),
    sa.Column('child_id', sa.Integer(), nullable=True),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('ended_utc', sa.DateTime(timezone=True), nullable=False),
    sa.Column('stars', sa.Integer(), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('finished', sa.Boolean(), nullable=False),
    sa.Column('steps_done', sa.Integer(), nullable=False),
    sa.Column('zaps', sa.Integer(), nullable=False),
    sa.Column('seconds', sa.JSON(), nullable=False),
    sa.Column('record', sa.JSON(), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('wash_id')
    )
    with op.batch_alter_table('washes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_washes_ended_utc'), ['ended_utc'], unique=False)
    op.create_table('app_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('parent_name', sa.String(length=64), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('daily_goal', sa.Integer(), nullable=False),
    sa.Column('routines', sa.JSON(), nullable=False),
    sa.Column('toggles', sa.JSON(), nullable=False),
    sa.Column('onboarded', sa.Boolean(), nullable=False),
    sa.Column('updated_utc', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('germ_unlocks',
    sa.Column('germ', sa.String(length=32), nullable=False),
    sa.Column('spent', sa.Integer(), nullable=False),
    sa.Column('how', sa.String(length=16), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('germ')
    )


def downgrade() -> None:
    op.drop_table('germ_unlocks')
    op.drop_table('app_settings')
    with op.batch_alter_table('washes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_washes_ended_utc'))
    op.drop_table('washes')
    op.drop_table('children')
