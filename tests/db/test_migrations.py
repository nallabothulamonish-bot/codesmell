from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from codesmell.config.settings import Settings
from codesmell.db import create_db_engine, schema_is_ready, upgrade_database


def test_packaged_migrations_create_m7_schema(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        workspace_root=tmp_path / "work",
        database={
            "url": f"sqlite:///{tmp_path / 'codesmell.db'}",
            "auto_migrate": False,
        },
        api={"storage_root": tmp_path / "data"},
    )
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        assert schema_is_ready(engine)
        assert {
            "projects",
            "analysis_jobs",
            "source_files",
            "entity_metrics",
            "findings",
            "job_events",
            "model_artifacts",
            "ml_predictions",
            "prediction_explanations",
            "recommendations",
            "alembic_version",
        }.issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()
