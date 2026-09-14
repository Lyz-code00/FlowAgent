"""add incident records and knowledge source urls

Revision ID: 20260914_0010
Revises: 20260913_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0010"
down_revision: str | None = "20260913_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents", sa.Column("source_url", sa.Text(), nullable=True)
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("incident_key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("service", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
            "tenant_id", "incident_key", name="uq_incident_tenant_key"
        ),
    )
    op.create_index("ix_incidents_tenant_id", "incidents", ["tenant_id"])
    op.create_index("ix_incidents_incident_key", "incidents", ["incident_key"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_service", "incidents", ["service"])
    op.create_index(
        "ix_incidents_created_by_user_id", "incidents", ["created_by_user_id"]
    )


def downgrade() -> None:
    op.drop_table("incidents")
    op.drop_column("knowledge_documents", "source_url")
