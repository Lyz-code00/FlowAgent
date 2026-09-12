"""GitHub tool write-operation idempotency.

Revision ID: 20260912_0002
Revises: 20260912_0001
Create Date: 2026-09-12
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260912_0002"
down_revision: str | None = "20260912_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("operation_id"),
    )
    op.create_index(
        "ix_tool_operations_operation_id",
        "tool_operations",
        ["operation_id"],
        unique=True,
    )
    op.create_index(
        "ix_tool_operations_conversation_id",
        "tool_operations",
        ["conversation_id"],
    )
    op.create_index(
        "ix_tool_operations_source_message_id",
        "tool_operations",
        ["source_message_id"],
    )
    op.create_index(
        "ix_tool_operations_user_id", "tool_operations", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("tool_operations")
