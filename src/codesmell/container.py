"""Composition root.

The only module allowed to know about both settings and concrete adapters.
Everything else receives its collaborators through constructor injection, which
is what makes the ingestion layer testable without a filesystem and the metrics
layer testable without a parser.

Registries live here so the active plugin set is a property of the container --
one container per process, one per test, no global mutable state leaking
between tests.
"""

from __future__ import annotations

from codesmell.config.logging import configure_logging, get_logger, safe_extra
from codesmell.config.settings import Settings, get_settings
from codesmell.core.enums import EntityType, Language, SmellType
from codesmell.core.ports import MetricCalculator, SmellDetector, SourceParser
from codesmell.core.registry import Registry
from codesmell.detectors import DetectionEngine, ThresholdMode, load_rules
from codesmell.detectors.engine import RuleBasedDetector
from codesmell.detectors.thresholds import ThresholdTable
from codesmell.ingestion.archive import SafeZipExtractor
from codesmell.ingestion.filters import PathFilter
from codesmell.ingestion.git import GitRepositoryFetcher
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.ingestion.sandbox import Workspace, WorkspaceManager
from codesmell.ingestion.service import IngestionService
from codesmell.languages.python import PythonParser
from codesmell.metrics import DEFAULT_CALCULATORS
from codesmell.metrics.engine import FeatureSchema, MetricsEngine

logger = get_logger(__name__)


class Container:
    """Builds and holds the application's long-lived objects."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

        self.parsers: Registry[Language, SourceParser] = Registry("parser")
        #: Keyed by calculator class name; ``applies_to`` on each calculator
        #: keeps class and method feature spaces separate, so the registry key
        #: does not need to encode entity type as well.
        self.metrics: Registry[str, MetricCalculator] = Registry(
            "metric_calculator"
        )
        #: Filled by the rule-based detectors at M3 and the ML ones at M5.
        self.detectors: Registry[SmellType, SmellDetector] = Registry("detector")

        self.workspaces = WorkspaceManager(
            self.settings.workspace_root, keep=self.settings.keep_workspaces
        )
        self.path_filter = PathFilter(
            max_file_bytes=self.settings.ingestion.max_source_file_bytes
        )
        self.repository_fetcher = GitRepositoryFetcher(self.settings.ingestion)

        self._register_default_plugins()

    def _register_default_plugins(self) -> None:
        """Wire the adapters that exist today.

        Explicit registration, not import-time magic: the active plugin set is
        inspectable via :meth:`describe` and swappable in a test.
        """
        self.parsers.register(Language.PYTHON, PythonParser())
        for calculator in DEFAULT_CALCULATORS:
            self.metrics.register(type(calculator).__name__, calculator)

        # Rules are validated against the live feature schema at load time: a
        # rule naming a metric that does not exist would otherwise never fire
        # and would report a clean project.
        self.rules = load_rules(
            self.settings.rules_path, schema=self.feature_schema
        )
        empty_table = ThresholdTable({})
        for rule in self.rules:
            self.detectors.register(
                rule.smell_type, RuleBasedDetector(rule, empty_table)
            )

    def metrics_engine(self) -> MetricsEngine:
        """Build the engine from whatever is currently registered."""
        return MetricsEngine(
            parsers=self.parsers.as_mapping(),
            calculators=self.metrics.values(),
        )

    @property
    def feature_schema(self) -> FeatureSchema:
        return FeatureSchema.from_calculators(self.metrics.values())

    def detection_engine(
        self, mode: ThresholdMode = ThresholdMode.ABSOLUTE
    ) -> DetectionEngine:
        """Build a detection engine over the loaded rule set."""
        return DetectionEngine(self.rules, mode)

    def ingestion_service(self, workspace: Workspace) -> IngestionService:
        """Build a per-job ingestion service bound to ``workspace``."""
        return IngestionService(
            self.settings.ingestion,
            workspace,
            path_filter=self.path_filter,
            extractor=SafeZipExtractor(self.settings.ingestion, workspace),
            fetcher=self.repository_fetcher,
            inventory_builder=ProjectInventoryBuilder(
                self.settings.ingestion, self.path_filter
            ),
        )

    def describe(self) -> dict[str, object]:
        """Startup banner content -- what is actually wired in right now."""
        return {
            "environment": self.settings.environment,
            "workspace_root": str(self.settings.workspace_root),
            "supported_languages": sorted(
                lang.value for lang in Language.supported()
            ),
            "parsers": len(self.parsers),
            "metric_calculators": len(self.metrics),
            "detectors": len(self.detectors),
            "rules": len(self.rules),
            "class_features": len(
                self.feature_schema.names_for(EntityType.CLASS)
            ),
            "method_features": len(
                self.feature_schema.names_for(EntityType.METHOD)
            ),
        }


def build_container(settings: Settings | None = None) -> Container:
    """Configure logging and construct the container. Call once at startup."""
    resolved = settings or get_settings()
    configure_logging(resolved.logging)
    container = Container(resolved)
    logger.info("container ready", extra=safe_extra(container.describe()))
    return container
