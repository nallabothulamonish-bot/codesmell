from pathlib import Path

from codesmell import __version__
from codesmell.api.app import create_app
from codesmell.config.settings import ApiSettings, Settings


def test_m8_version_and_frontend_sources_exist() -> None:
    assert __version__ == "0.7.0"
    root = Path(__file__).parents[1]
    required = [
        root / "frontend" / "package.json",
        root / "frontend" / "src" / "App.tsx",
        root / "frontend" / "src" / "pages" / "DashboardPage.tsx",
        root / "frontend" / "src" / "pages" / "AnalysisDetailPage.tsx",
        root / "frontend" / "nginx.conf",
        root / "frontend" / "Dockerfile",
    ]
    assert all(path.is_file() for path in required)


def test_cors_supports_model_registry_patch(tmp_path: Path) -> None:
    settings = Settings(
        database={"url": f"sqlite:///{tmp_path / 'm8.db'}", "auto_migrate": True},
        api=ApiSettings(storage_root=tmp_path / "data", cors_origins=("http://localhost:5173",)),
        workspace_root=tmp_path / "workspaces",
    )
    app = create_app(settings)
    middleware = [item for item in app.user_middleware if item.cls.__name__ == "CORSMiddleware"]
    assert middleware
    assert "PATCH" in middleware[0].kwargs["allow_methods"]
