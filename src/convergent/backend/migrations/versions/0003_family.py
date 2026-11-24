"""family: several children with one active, family rewards, redemptions, high-fives, per-child germs

Revision ID: 0003_family
Revises: 0002_parent_app
Create Date: 2026-11-24

Existing data is kept. Germs bought before this change move to the first child (or stay
unassigned until a child is added); washes keep their child.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0003_family'
down_revision = '0002_parent_app'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('washes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reward_points', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('source', sa.String(length=16), nullable=False, server_default='station'))
    with op.batch_alter_table('app_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active_child_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('parent_pin_hash', sa.String(length=200), nullable=True))

    op.create_table('child_germs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('child_id', sa.Integer(), nullable=True),
    sa.Column('germ', sa.String(length=32), nullable=False),
    sa.Column('spent', sa.Integer(), nullable=False),
    sa.Column('how', sa.String(length=16), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('child_id', 'germ', name='uq_child_germ')
    )
    with op.batch_alter_table('child_germs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_child_germs_child_id'), ['child_id'], unique=False)
    op.execute("INSERT INTO child_germs (child_id, germ, spent, how, created_utc) "
               "SELECT (SELECT MIN(id) FROM children), germ, spent, how, created_utc FROM germ_unlocks")
    op.drop_table('germ_unlocks')
    # washes saved before any child existed belong to the first child once there is one
    op.execute("UPDATE washes SET child_id = (SELECT MIN(id) FROM children) WHERE child_id IS NULL")
    op.execute("UPDATE washes SET source = 'demo' WHERE wash_id LIKE 'demo-%'")

    op.create_table('family_rewards',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('title', sa.String(length=80), nullable=False),
    sa.Column('cost', sa.Integer(), nullable=False),
    sa.Column('icon', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('cost > 0', name='ck_family_rewards_cost_positive'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('redemptions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('child_id', sa.Integer(), nullable=True),
    sa.Column('reward_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=80), nullable=False),
    sa.Column('cost', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('requested_utc', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_utc', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('requested', 'approved', 'declined')", name='ck_redemptions_status'),
    sa.CheckConstraint('cost > 0', name='ck_redemptions_cost_positive'),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reward_id'], ['family_rewards.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_id')
    )
    with op.batch_alter_table('redemptions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_redemptions_child_id'), ['child_id'], unique=False)
    op.create_table('encouragements',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('wash_id', sa.String(length=96), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['wash_id'], ['washes.wash_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wash_id', 'kind', name='uq_encouragement_wash_kind')
    )


def downgrade() -> None:
    op.drop_table('encouragements')
    with op.batch_alter_table('redemptions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_redemptions_child_id'))
    op.drop_table('redemptions')
    op.drop_table('family_rewards')
    op.create_table('germ_unlocks',
    sa.Column('germ', sa.String(length=32), nullable=False),
    sa.Column('spent', sa.Integer(), nullable=False),
    sa.Column('how', sa.String(length=16), nullable=False),
    sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('germ')
    )
    op.execute("INSERT INTO germ_unlocks (germ, spent, how, created_utc) "
               "SELECT germ, MAX(spent), MIN(how), MIN(created_utc) FROM child_germs GROUP BY germ")
    with op.batch_alter_table('child_germs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_child_germs_child_id'))
    op.drop_table('child_germs')
    with op.batch_alter_table('app_settings', schema=None) as batch_op:
        batch_op.drop_column('parent_pin_hash')
        batch_op.drop_column('active_child_id')
    with op.batch_alter_table('washes', schema=None) as batch_op:
        batch_op.drop_column('source')
        batch_op.drop_column('reward_points')
