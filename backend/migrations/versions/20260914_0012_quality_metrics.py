"""add inbound event audit metrics

Revision ID: 20260914_0012
Revises: 20260914_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0012"
down_revision: str | None = "20260914_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbound_event_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=False),
        sa.Column("duplicate", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_inbound_event_audits_created_at",
        "inbound_event_audits",
        ["created_at"],
    )
    op.create_index(
        "ix_inbound_event_audits_platform_message",
        "inbound_event_audits",
        ["platform", "external_message_id"],
    )


def downgrade() -> None:
    op.drop_table("inbound_event_audits")
