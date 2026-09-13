"""add high-risk action confirmations

Revision ID: 20260913_0009
Revises: 20260913_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0009"
down_revision: str | None = "20260913_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("code", name="uq_action_confirmations_code"),
    )
    op.create_index("ix_action_confirmations_code", "action_confirmations", ["code"], unique=True)
    op.create_index("ix_action_confirmations_tool_name", "action_confirmations", ["tool_name"])
    op.create_index("ix_action_confirmations_conversation_id", "action_confirmations", ["conversation_id"])
    op.create_index("ix_action_confirmations_user_id", "action_confirmations", ["user_id"])
    op.create_index("ix_action_confirmations_status", "action_confirmations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_action_confirmations_status", table_name="action_confirmations")
    op.drop_index("ix_action_confirmations_user_id", table_name="action_confirmations")
    op.drop_index("ix_action_confirmations_conversation_id", table_name="action_confirmations")
    op.drop_index("ix_action_confirmations_tool_name", table_name="action_confirmations")
    op.drop_index("ix_action_confirmations_code", table_name="action_confirmations")
    op.drop_table("action_confirmations")
