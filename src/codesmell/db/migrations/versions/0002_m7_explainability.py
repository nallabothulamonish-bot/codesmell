"""M7 registered models, predictions, explanations and recommendations.

Revision ID: 0002_m7
Revises: 0001_m6
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_m7"
down_revision: Union[str, None] = "0001_m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("model_ids", sa.JSON(), nullable=True))
    op.add_column(
        "analysis_jobs",
        sa.Column("explain_predictions", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "model_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("smell_type", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("model_kind", sa.String(length=40), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("model_sha256", sa.String(length=64), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("feature_names", sa.JSON(), nullable=False),
        sa.Column("model_card", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_artifacts")),
        sa.UniqueConstraint("model_sha256", name=op.f("uq_model_artifacts_model_sha256")),
    )
    op.create_index(op.f("ix_model_artifacts_smell_type"), "model_artifacts", ["smell_type"])
    op.create_index(op.f("ix_model_artifacts_entity_type"), "model_artifacts", ["entity_type"])
    op.create_index(op.f("ix_model_artifacts_model_kind"), "model_artifacts", ["model_kind"])
    op.create_index(op.f("ix_model_artifacts_enabled"), "model_artifacts", ["enabled"])

    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("smell_type", sa.String(length=80), nullable=False),
        sa.Column("prediction", sa.Boolean(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("uncertainty", sa.Float(), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE", name=op.f("fk_ml_predictions_job_id_analysis_jobs")),
        sa.ForeignKeyConstraint(["model_id"], ["model_artifacts.id"], ondelete="RESTRICT", name=op.f("fk_ml_predictions_model_id_model_artifacts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_predictions")),
        sa.UniqueConstraint("job_id", "model_id", "entity_id", name=op.f("uq_ml_predictions_job_id")),
    )
    op.create_index(op.f("ix_ml_predictions_job_id"), "ml_predictions", ["job_id"])
    op.create_index(op.f("ix_ml_predictions_model_id"), "ml_predictions", ["model_id"])
    op.create_index(op.f("ix_ml_predictions_smell_type"), "ml_predictions", ["smell_type"])
    op.create_index(op.f("ix_ml_predictions_prediction"), "ml_predictions", ["prediction"])
    op.create_index(op.f("ix_ml_predictions_relative_path"), "ml_predictions", ["relative_path"])
    op.create_index("ix_ml_predictions_job_smell", "ml_predictions", ["job_id", "smell_type"])

    op.create_table(
        "prediction_explanations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=80), nullable=False),
        sa.Column("base_value", sa.Float(), nullable=True),
        sa.Column("output_value", sa.Float(), nullable=True),
        sa.Column("top_features", sa.JSON(), nullable=False),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["ml_predictions.id"], ondelete="CASCADE", name=op.f("fk_prediction_explanations_prediction_id_ml_predictions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prediction_explanations")),
        sa.UniqueConstraint("prediction_id", name=op.f("uq_prediction_explanations_prediction_id")),
    )
    op.create_index(op.f("ix_prediction_explanations_prediction_id"), "prediction_explanations", ["prediction_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("smell_type", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("validation_steps", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE", name=op.f("fk_recommendations_job_id_analysis_jobs")),
        sa.ForeignKeyConstraint(["prediction_id"], ["ml_predictions.id"], ondelete="CASCADE", name=op.f("fk_recommendations_prediction_id_ml_predictions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        sa.UniqueConstraint("prediction_id", name=op.f("uq_recommendations_prediction_id")),
    )
    op.create_index(op.f("ix_recommendations_job_id"), "recommendations", ["job_id"])
    op.create_index(op.f("ix_recommendations_prediction_id"), "recommendations", ["prediction_id"])
    op.create_index(op.f("ix_recommendations_smell_type"), "recommendations", ["smell_type"])
    op.create_index(op.f("ix_recommendations_priority"), "recommendations", ["priority"])
    op.create_index("ix_recommendations_job_smell", "recommendations", ["job_id", "smell_type"])


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("prediction_explanations")
    op.drop_table("ml_predictions")
    op.drop_table("model_artifacts")
    op.drop_column("analysis_jobs", "explain_predictions")
    op.drop_column("analysis_jobs", "model_ids")
