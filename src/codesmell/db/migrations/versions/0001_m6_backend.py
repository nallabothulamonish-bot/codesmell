"""M6 backend, projects, jobs, metrics and findings.

Revision ID: 0001_m6
Revises:
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_m6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("stored_path", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("inventory_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(op.f("ix_projects_content_sha256"), "projects", ["content_sha256"])
    op.create_index(op.f("ix_projects_fingerprint"), "projects", ["fingerprint"])
    op.create_index(op.f("ix_projects_status"), "projects", ["status"])

    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("analysis_kind", sa.String(length=24), nullable=False),
        sa.Column("threshold_mode", sa.String(length=24), nullable=False),
        sa.Column("min_severity", sa.String(length=24), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("progress_message", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_analysis_jobs_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_jobs")),
    )
    op.create_index(op.f("ix_analysis_jobs_project_id"), "analysis_jobs", ["project_id"])
    op.create_index(op.f("ix_analysis_jobs_queued_at"), "analysis_jobs", ["queued_at"])
    op.create_index(op.f("ix_analysis_jobs_status"), "analysis_jobs", ["status"])
    op.create_index("ix_analysis_jobs_queue", "analysis_jobs", ["status", "queued_at"])

    op.create_table(
        "source_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_source_files_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_files")),
        sa.UniqueConstraint("project_id", "relative_path", name=op.f("uq_source_files_project_id")),
    )
    op.create_index(op.f("ix_source_files_project_id"), "source_files", ["project_id"])

    op.create_table(
        "entity_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["analysis_jobs.id"], name=op.f("fk_entity_metrics_job_id_analysis_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_metrics")),
        sa.UniqueConstraint("job_id", "entity_id", name=op.f("uq_entity_metrics_job_id")),
    )
    op.create_index(op.f("ix_entity_metrics_entity_type"), "entity_metrics", ["entity_type"])
    op.create_index(op.f("ix_entity_metrics_job_id"), "entity_metrics", ["job_id"])
    op.create_index(op.f("ix_entity_metrics_relative_path"), "entity_metrics", ["relative_path"])
    op.create_index("ix_entity_metrics_job_type", "entity_metrics", ["job_id", "entity_type"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("smell_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("detector", sa.String(length=160), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("threshold_mode", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["analysis_jobs.id"], name=op.f("fk_findings_job_id_analysis_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index(op.f("ix_findings_job_id"), "findings", ["job_id"])
    op.create_index(op.f("ix_findings_relative_path"), "findings", ["relative_path"])
    op.create_index(op.f("ix_findings_severity"), "findings", ["severity"])
    op.create_index(op.f("ix_findings_smell_type"), "findings", ["smell_type"])
    op.create_index("ix_findings_job_smell", "findings", ["job_id", "smell_type"])
    op.create_index("ix_findings_job_severity", "findings", ["job_id", "severity"])

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["analysis_jobs.id"], name=op.f("fk_job_events_job_id_analysis_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_events")),
    )
    op.create_index(op.f("ix_job_events_job_id"), "job_events", ["job_id"])


def downgrade() -> None:
    op.drop_table("job_events")
    op.drop_table("findings")
    op.drop_table("entity_metrics")
    op.drop_table("source_files")
    op.drop_table("analysis_jobs")
    op.drop_table("projects")
