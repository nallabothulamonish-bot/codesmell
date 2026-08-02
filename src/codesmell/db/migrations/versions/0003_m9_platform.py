"""M9 authentication, reports and audit trail.

Revision ID: 0003_m9
Revises: 0002_m7
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_m9"
down_revision: Union[str, None] = "0002_m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"])
    op.create_index(op.f("ix_users_role"), "users", ["role"])
    op.create_index(op.f("ix_users_enabled"), "users", ["enabled"])

    op.create_table(
        "generated_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=True),
        sa.Column("format", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE", name=op.f("fk_generated_reports_job_id_analysis_jobs")),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL", name=op.f("fk_generated_reports_requested_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_reports")),
    )
    op.create_index(op.f("ix_generated_reports_job_id"), "generated_reports", ["job_id"])
    op.create_index(op.f("ix_generated_reports_requested_by"), "generated_reports", ["requested_by"])
    op.create_index(op.f("ix_generated_reports_format"), "generated_reports", ["format"])
    op.create_index(op.f("ix_generated_reports_status"), "generated_reports", ["status"])
    op.create_index(op.f("ix_generated_reports_content_sha256"), "generated_reports", ["content_sha256"])
    op.create_index("ix_generated_reports_job_format", "generated_reports", ["job_id", "format"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=True),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL", name=op.f("fk_audit_events_actor_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_actor_user_id"), "audit_events", ["actor_user_id"])
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"])
    op.create_index(op.f("ix_audit_events_resource_type"), "audit_events", ["resource_type"])
    op.create_index(op.f("ix_audit_events_resource_id"), "audit_events", ["resource_id"])
    op.create_index(op.f("ix_audit_events_request_id"), "audit_events", ["request_id"])
    op.create_index(op.f("ix_audit_events_created_at"), "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("generated_reports")
    op.drop_table("users")
