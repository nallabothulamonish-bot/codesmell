"""M1: intake, sandboxing, filtering and project inventory."""

from codesmell.ingestion.archive import SafeZipExtractor
from codesmell.ingestion.detection import (
    BuildToolDetector,
    DependencyDetector,
    FrameworkDetector,
    LanguageDetector,
)
from codesmell.ingestion.filters import PathFilter
from codesmell.ingestion.git import GitRepositoryFetcher
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.ingestion.sandbox import Workspace, WorkspaceManager
from codesmell.ingestion.service import IngestionService

__all__ = [
    "BuildToolDetector",
    "DependencyDetector",
    "FrameworkDetector",
    "GitRepositoryFetcher",
    "IngestionService",
    "LanguageDetector",
    "PathFilter",
    "ProjectInventoryBuilder",
    "SafeZipExtractor",
    "Workspace",
    "WorkspaceManager",
]
