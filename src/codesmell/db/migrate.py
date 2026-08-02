"""Programmatic Alembic entry points used by CLI and application startup."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from codesmell.config.settings import Settings


def alembic_config(settings: Settings) -> Config:
    config = Config()
    script_location = Path(__file__).resolve().parent / "migrations"
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", settings.database.url.replace("%", "%%"))
    return config


def upgrade_database(settings: Settings, revision: str = "head") -> None:
    command.upgrade(alembic_config(settings), revision)


def downgrade_database(settings: Settings, revision: str) -> None:
    command.downgrade(alembic_config(settings), revision)


def schema_is_ready(engine: Engine) -> bool:
    tables = set(inspect(engine).get_table_names())
    return {"projects", "analysis_jobs", "entity_metrics", "findings", "model_artifacts", "ml_predictions", "users", "generated_reports"}.issubset(tables)
