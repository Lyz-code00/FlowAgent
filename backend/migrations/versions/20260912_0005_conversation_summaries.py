"""add structured conversation summaries

Revision ID: 20260912_0005
Revises: 20260912_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0005"
down_revision: str | None = "20260912_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("bugs", sa.JSON(), nullable=False),
        sa.Column("action_items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_conversation_summaries_tenant_id", "conversation_summaries", ["tenant_id"])
    op.create_index("ix_conversation_summaries_conversation_id", "conversation_summaries", ["conversation_id"])
    op.create_index("ix_conversation_summaries_created_by_user_id", "conversation_summaries", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_table("conversation_summaries")
