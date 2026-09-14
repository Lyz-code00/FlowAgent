"""add service ownership mappings

Revision ID: 20260914_0011
Revises: 20260914_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0011"
down_revision: str | None = "20260914_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ownership_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service", sa.String(length=255), nullable=False),
        sa.Column("team", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("feishu_open_id", sa.String(length=255), nullable=False),
        sa.Column("github_username", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint(
            "tenant_id", "service", name="uq_owner_tenant_service"
        ),
    )
    for column in ("tenant_id", "service", "team", "active"):
        op.create_index(
            f"ix_ownership_mappings_{column}", "ownership_mappings", [column]
        )


def downgrade() -> None:
    op.drop_table("ownership_mappings")
