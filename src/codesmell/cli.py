"""Command-line interface.

``codesmell ingest`` is the M1 acceptance test made runnable: point it at a
directory, a ZIP, a single file or a GitHub URL and it prints the inventory the
rest of the pipeline will consume.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from codesmell import __version__
from codesmell.config.settings import Settings, get_settings
from codesmell.container import build_container
from codesmell.core.enums import EntityType, Severity
from codesmell.core.errors import CodeSmellError
from codesmell.core.models import ProjectInventory
from codesmell.dataset import (
    DatasetWriter,
    LabelDatasetBuilder,
    SamplingConfig,
    reviewer_agreement,
    validate_review_file,
    write_final_labels,
)
from codesmell.detectors import DetectionReport, ThresholdMode
from codesmell.metrics.engine import AnalysisResult
from codesmell.ml import (
    ModelKind,
    TrainingConfig,
    leave_one_project_out,
    load_training_dataset,
    predict_with_model,
    prepare_feature_dataset,
    train_holdout,
    write_split_assignments,
)
from codesmell.ml.io import PREDICTION_COLUMNS, write_csv as write_ml_csv

app = typer.Typer(
    name="codesmell",
    help="Explainable and cross-project code smell detection.",
    no_args_is_help=True,
    add_completion=False,
)

class _ConsoleProxy:
    def __getattr__(self, name: str):
        return getattr(Console(), name)

console = _ConsoleProxy()
dataset_app = typer.Typer(
    name="dataset",
    help="M4 blinded human-labelling dataset workflow.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(dataset_app, name="dataset")
ml_app = typer.Typer(
    name="ml",
    help="M5 leakage-safe model training and cross-project evaluation.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(ml_app, name="ml")
api_app = typer.Typer(
    name="api",
    help="M6 FastAPI backend service.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(api_app, name="api")
db_app = typer.Typer(
    name="db",
    help="M6 database migrations.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(db_app, name="db")
worker_app = typer.Typer(
    name="worker",
    help="M6 persistent background analysis worker.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(worker_app, name="worker")
model_app = typer.Typer(
    name="model",
    help="M7 trusted model registry administration.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(model_app, name="model")
user_app = typer.Typer(
    name="user",
    help="M9 user and role administration.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(user_app, name="user")
report_app = typer.Typer(
    name="report",
    help="M9 stored analysis-report generation.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(report_app, name="report")
research_app = typer.Typer(
    name="research",
    help="M9 publication-oriented evaluation exports.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(research_app, name="research")


@app.command()
def version() -> None:
    """Print the package version."""
    console.print(f"codesmell {__version__}")


@app.command()
def config() -> None:
    """Show the effective configuration and wired plugins."""
    container = build_container()
    console.print_json(json.dumps(container.describe(), indent=2))


@app.command()
def ingest(
    source: Annotated[
        str,
        typer.Argument(
            help="Directory, .zip archive, source file, or https:// repo URL."
        ),
    ],
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the inventory as JSON.")
    ] = False,
    show_rejections: Annotated[
        bool,
        typer.Option("--rejections", help="List every refused file."),
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Rows shown in the file table.")
    ] = 20,
) -> None:
    """Ingest a project and print its inventory."""
    settings = _cli_settings()
    container = build_container(settings)

    try:
        with container.workspaces.session() as workspace:
            service = container.ingestion_service(workspace)
            result = service.ingest(source)

            if as_json:
                console.print_json(
                    json.dumps(result.inventory.summary(), indent=2)
                )
            else:
                _render(result.inventory, limit=limit, rejections=show_rejections)

            for warning in result.warnings:
                console.print(f"[yellow]warning:[/yellow] {warning}")

    except CodeSmellError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        if exc.details:
            console.print_json(json.dumps(exc.details, default=str, indent=2))
        raise typer.Exit(code=1) from exc


@app.command()
def analyze(
    source: Annotated[
        str,
        typer.Argument(
            help="Directory, .zip archive, source file, or https:// repo URL."
        ),
    ],
    entity_type: Annotated[
        str,
        typer.Option("--type", help="class, method, function or module."),
    ] = "class",
    sort_by: Annotated[
        str, typer.Option("--sort", help="Metric to rank entities by.")
    ] = "wmc",
    limit: Annotated[int, typer.Option("--limit")] = 15,
) -> None:
    """Ingest a project, extract every software metric, and rank the results."""
    settings = _cli_settings()
    container = build_container(settings)

    try:
        kind = EntityType(entity_type.lower())
    except ValueError:
        console.print(
            f"[red]unknown entity type:[/red] {entity_type} "
            f"(expected one of {', '.join(e.value for e in EntityType)})"
        )
        raise typer.Exit(code=2) from None

    try:
        with container.workspaces.session() as workspace:
            ingested = container.ingestion_service(workspace).ingest(source)
            result = container.metrics_engine().analyze(
                ingested.root, ingested.inventory
            )
            _render_analysis(result, kind, sort_by=sort_by, limit=limit)

            for warning in ingested.warnings:
                console.print(f"[yellow]warning:[/yellow] {warning}")

    except CodeSmellError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        if exc.details:
            console.print_json(json.dumps(exc.details, default=str, indent=2))
        raise typer.Exit(code=1) from exc


def _render_analysis(
    result: AnalysisResult, entity_type: EntityType, *, sort_by: str, limit: int
) -> None:
    console = Console(file=sys.stdout, width=200)
    summary = Table(title=f"Analysis: {result.inventory.name}", show_header=False)
    summary.add_column("field", style="cyan")
    summary.add_column("value")
    for key, value in result.summary().items():
        summary.add_row(key.replace("_", " ").title(), str(value))
    console.print(summary)

    vectors = result.vectors_for(entity_type)
    if not vectors:
        console.print(f"[yellow]no {entity_type.value} entities found[/yellow]")
        return

    names = result.schema.names_for(entity_type)
    if sort_by not in names:
        console.print(
            f"[yellow]unknown metric {sort_by!r}; falling back to loc. "
            f"Available: {', '.join(names)}[/yellow]"
        )
        sort_by = "loc"

    headline = [
        name
        for name in ("loc", "wmc", "cbo", "lcom_hs", "dit", "rfc",
                     "cyclomatic_complexity", "cognitive_complexity",
                     "parameter_count", "maintainability_index")
        if name in names
    ]

    table = Table(title=f"Top {limit} {entity_type.value}es by {sort_by}")
    table.add_column("entity", style="green", overflow="fold")
    for name in headline:
        table.add_column(_abbreviate(name), justify="right")

    ranked = sorted(vectors, key=lambda v: v.get(sort_by), reverse=True)[:limit]
    for vector in ranked:
        entity = result.context.entity_by_id(vector.entity_id)
        label = entity.qualified_name if entity else vector.entity_id
        table.add_row(label, *(_format(vector.get(n)) for n in headline))
    console.print(table)


def _abbreviate(name: str) -> str:
    return {
        "cyclomatic_complexity": "cc",
        "cognitive_complexity": "cog",
        "maintainability_index": "mi",
        "parameter_count": "params",
    }.get(name, name)


def _format(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


@app.command()
def detect(
    source: Annotated[
        str,
        typer.Argument(
            help="Directory, .zip archive, source file, or https:// repo URL."
        ),
    ],
    mode: Annotated[
        str,
        typer.Option(
            "--thresholds",
            help="'absolute' (literature values) or 'percentile' (per-project).",
        ),
    ] = "absolute",
    min_severity: Annotated[
        str, typer.Option("--min-severity", help="low, medium, high or critical.")
    ] = "low",
    explain: Annotated[
        bool,
        typer.Option("--explain", help="Show the condition trail for each finding."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit findings as JSON, for export or human adjudication.",
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit")] = 25,
) -> None:
    """Detect code smells using the rule-based baseline (no ML involved)."""
    settings = _cli_settings()
    container = build_container(settings)

    try:
        threshold_mode = ThresholdMode(mode.lower())
    except ValueError:
        console.print(
            f"[red]unknown threshold mode:[/red] {mode} "
            "(expected 'absolute' or 'percentile')"
        )
        raise typer.Exit(code=2) from None

    try:
        floor = Severity(min_severity.lower())
    except ValueError:
        console.print(f"[red]unknown severity:[/red] {min_severity}")
        raise typer.Exit(code=2) from None

    try:
        with container.workspaces.session() as workspace:
            ingested = container.ingestion_service(workspace).ingest(source)
            analysis = container.metrics_engine().analyze(
                ingested.root, ingested.inventory
            )
            report = container.detection_engine(threshold_mode).detect(analysis)

            if as_json:
                console.print_json(
                    json.dumps(report.to_dict(), default=str, indent=2)
                )
            else:
                _render_detections(
                    report, floor=floor, limit=limit, explain=explain
                )
                for warning in ingested.warnings:
                    console.print(f"[yellow]warning:[/yellow] {warning}")

    except CodeSmellError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        if exc.details:
            console.print_json(json.dumps(exc.details, default=str, indent=2))
        raise typer.Exit(code=1) from exc


_SEVERITY_STYLE = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
}


def _render_detections(
    report: DetectionReport, *, floor: Severity, limit: int, explain: bool
) -> None:
    overview = Table(title="Detection summary", show_header=False)
    overview.add_column("field", style="cyan")
    overview.add_column("value")
    overview.add_row("Threshold mode", report.threshold_mode.value)
    overview.add_row("Rules applied", str(report.rules_applied))
    overview.add_row("Entities examined", f"{report.entities_examined:,}")
    overview.add_row("Findings", str(len(report.findings)))
    for severity, count in report.counts_by_severity().items():
        overview.add_row(f"  {severity}", str(count))
    console.print(overview)

    if report.skipped_rules:
        console.print(
            f"[yellow]{len(report.skipped_rules)} rule(s) skipped in "
            f"{report.threshold_mode.value} mode:[/yellow] "
            + ", ".join(sorted(report.skipped_rules))
        )

    if not report.findings:
        console.print("[green]no smells detected[/green]")
        return

    by_smell = Table(title="Findings by smell")
    by_smell.add_column("smell", style="magenta")
    by_smell.add_column("count", justify="right")
    for smell, count in report.counts_by_smell().items():
        by_smell.add_row(smell, str(count))
    console.print(by_smell)

    shown = [f for f in report.findings if f.severity.rank >= floor.rank][:limit]
    if not shown:
        console.print(f"[green]no findings at {floor.value} or above[/green]")
        return

    table = Table(title=f"Top {len(shown)} findings")
    table.add_column("severity")
    table.add_column("smell", style="magenta")
    table.add_column("entity", style="green", overflow="fold")
    table.add_column("location", overflow="fold")

    for finding in shown:
        table.add_row(
            f"[{_SEVERITY_STYLE[finding.severity]}]{finding.severity.value}[/]",
            finding.smell_type.value,
            finding.entity.qualified_name,
            f"{finding.entity.relative_path}:{finding.entity.start_line}",
        )
    console.print(table)

    if explain:
        console.print()
        for finding in shown:
            console.print(finding.explain())
            console.print()


@dataset_app.command("create")
def dataset_create(
    sources: Annotated[
        list[str],
        typer.Argument(
            help="One or more directories, ZIP files, source files, or HTTPS repos."
        ),
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Output dataset directory.")
    ] = Path("dataset_m4"),
    mode: Annotated[
        str,
        typer.Option(
            "--thresholds",
            help="Candidate generation mode: absolute or percentile.",
        ),
    ] = "absolute",
    negative_ratio: Annotated[
        float,
        typer.Option(
            "--negative-ratio",
            min=0.0,
            help="Sampled controls per rule candidate.",
        ),
    ] = 1.0,
    min_controls: Annotated[
        int,
        typer.Option(
            "--min-controls",
            min=0,
            help="Minimum controls sampled for each smell, even with no finding.",
        ),
    ] = 3,
    seed: Annotated[
        int, typer.Option("--seed", help="Reproducible control-sampling seed.")
    ] = 42,
    max_snippet_lines: Annotated[
        int,
        typer.Option(
            "--max-snippet-lines",
            min=1,
            help="Maximum source lines saved for one entity snippet.",
        ),
    ] = 200,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace a non-empty output directory.")
    ] = False,
) -> None:
    """Create blinded review tasks, separate rule evidence, and code snippets."""
    try:
        threshold_mode = ThresholdMode(mode.lower())
    except ValueError:
        console.print(
            f"[red]unknown threshold mode:[/red] {mode} "
            "(expected 'absolute' or 'percentile')"
        )
        raise typer.Exit(code=2) from None

    settings = _cli_settings()
    container = build_container(settings)
    config = SamplingConfig(
        negative_ratio=negative_ratio,
        min_controls_per_smell=min_controls,
        seed=seed,
        max_snippet_lines=max_snippet_lines,
    )
    builder = LabelDatasetBuilder(config)
    bundles = []

    try:
        for source in sources:
            with container.workspaces.session() as workspace:
                ingested = container.ingestion_service(workspace).ingest(source)
                analysis = container.metrics_engine().analyze(
                    ingested.root, ingested.inventory
                )
                detection = container.detection_engine(threshold_mode).detect(analysis)
                bundles.append(
                    builder.build_project(analysis, detection, container.rules)
                )
                for warning in ingested.warnings:
                    console.print(
                        f"[yellow]warning ({ingested.inventory.name}):[/yellow] "
                        f"{warning}"
                    )

        report = DatasetWriter().write(
            bundles, output, container.rules, config, overwrite=overwrite
        )
        _render_dataset_build(report.to_dict())
    except (CodeSmellError, ValueError) as exc:
        if isinstance(exc, CodeSmellError):
            console.print(f"[red]{exc.code}:[/red] {exc.message}")
            if exc.details:
                console.print_json(json.dumps(exc.details, default=str, indent=2))
        else:
            console.print(f"[red]dataset_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@dataset_app.command("validate")
def dataset_validate(
    review_file: Annotated[
        Path, typer.Argument(help="Completed or partially completed review_tasks.csv.")
    ],
    require_complete: Annotated[
        bool,
        typer.Option(
            "--require-complete",
            help="Treat blank human labels as validation errors.",
        ),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the validation report as JSON.")
    ] = False,
) -> None:
    """Validate labels, severities, reviewer IDs, columns, and task uniqueness."""
    try:
        report = validate_review_file(review_file, require_complete=require_complete)
    except CodeSmellError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(report.to_dict(), indent=2))
    else:
        _render_validation(report.to_dict())
        for issue in report.issues[:25]:
            console.print(
                f"[red]row {issue.row_number}[/red] "
                f"{issue.task_id or '-'} [{issue.field}]: {issue.message}"
            )
        if len(report.issues) > 25:
            console.print(f"[yellow]... {len(report.issues) - 25} more issues[/yellow]")

    if not report.valid:
        raise typer.Exit(code=1)


@dataset_app.command("finalize")
def dataset_finalize(
    review_file: Annotated[
        Path, typer.Argument(help="A completed and validated review_tasks.csv.")
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Canonical labels CSV.")
    ] = Path("labels.csv"),
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace the output file.")
    ] = False,
) -> None:
    """Export labels only; omit uncertain decisions and all rule/metric evidence."""
    try:
        validation = validate_review_file(review_file, require_complete=True)
        if not validation.valid:
            _render_validation(validation.to_dict())
            for issue in validation.issues[:25]:
                console.print(
                    f"[red]row {issue.row_number}[/red] "
                    f"{issue.task_id or '-'} [{issue.field}]: {issue.message}"
                )
            raise typer.Exit(code=1)
        manifest = write_final_labels(
            review_file, output, overwrite=overwrite
        )
        console.print_json(json.dumps(manifest, indent=2))
    except typer.Exit:
        raise
    except CodeSmellError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        if exc.details:
            console.print_json(json.dumps(exc.details, default=str, indent=2))
        raise typer.Exit(code=1) from exc


@dataset_app.command("agreement")
def dataset_agreement(
    first_review: Annotated[Path, typer.Argument(help="First reviewer CSV.")],
    second_review: Annotated[Path, typer.Argument(help="Second reviewer CSV.")],
    conflicts: Annotated[
        Path | None,
        typer.Option(
            "--conflicts",
            help="Optional CSV destination for disagreements requiring adjudication.",
        ),
    ] = None,
) -> None:
    """Calculate exact agreement and Cohen's kappa for two reviewers."""
    try:
        report = reviewer_agreement(
            first_review, second_review, conflicts_output=conflicts
        )
        console.print_json(json.dumps(report, indent=2))
    except CodeSmellError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        if exc.details:
            console.print_json(json.dumps(exc.details, default=str, indent=2))
        raise typer.Exit(code=1) from exc



@ml_app.command("prepare")
def ml_prepare(
    labels_file: Annotated[
        Path, typer.Argument(help="Canonical labels.csv produced by M4 finalize.")
    ],
    sources: Annotated[
        list[str],
        typer.Argument(
            help="Original project directories, ZIPs, files, or HTTPS repositories."
        ),
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Verified feature dataset CSV.")
    ] = Path("training_features.csv"),
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace an existing output file.")
    ] = False,
) -> None:
    """Recompute metrics from source and join them to human labels."""
    settings = _cli_settings()
    container = build_container(settings)
    analyses = []
    try:
        for source in sources:
            with container.workspaces.session() as workspace:
                ingested = container.ingestion_service(workspace).ingest(source)
                analyses.append(
                    container.metrics_engine().analyze(
                        ingested.root, ingested.inventory
                    )
                )
                for warning in ingested.warnings:
                    console.print(
                        f"[yellow]warning ({ingested.inventory.name}):[/yellow] "
                        f"{warning}"
                    )
        manifest = prepare_feature_dataset(
            labels_file, analyses, output, overwrite=overwrite
        )
        _render_ml_prepare(manifest)
    except (CodeSmellError, ValueError) as exc:
        _render_ml_error(exc)
        raise typer.Exit(code=1) from exc


@ml_app.command("split")
def ml_split(
    dataset_file: Annotated[
        Path, typer.Argument(help="M5 training_features.csv.")
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Per-smell split assignments CSV.")
    ] = Path("project_split.csv"),
    test_size: Annotated[
        float, typer.Option("--test-size", min=0.01, max=0.99)
    ] = 0.2,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    smell: Annotated[
        list[str] | None,
        typer.Option(
            "--smell",
            help="Repeat to restrict the split to selected smells.",
        ),
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Write deterministic train/test assignments with project-level isolation."""
    try:
        dataset = load_training_dataset(dataset_file)
        selected = _parse_smells(smell, dataset.smells)
        report = write_split_assignments(
            dataset,
            output,
            test_size=test_size,
            seed=seed,
            smell_types=selected,
            overwrite=overwrite,
        )
        _render_ml_split(report)
    except (CodeSmellError, ValueError) as exc:
        _render_ml_error(exc)
        raise typer.Exit(code=1) from exc


@ml_app.command("train")
def ml_train(
    dataset_file: Annotated[
        Path, typer.Argument(help="M5 training_features.csv.")
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Model artefact directory.")
    ] = Path("models_m5"),
    models: Annotated[
        str,
        typer.Option(
            "--models",
            help="Comma-separated: logistic,random_forest.",
        ),
    ] = "logistic,random_forest",
    test_size: Annotated[
        float, typer.Option("--test-size", min=0.01, max=0.99)
    ] = 0.2,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    threshold: Annotated[
        float, typer.Option("--threshold", min=0.01, max=0.99)
    ] = 0.5,
    min_samples: Annotated[
        int, typer.Option("--min-samples", min=2)
    ] = 10,
    min_projects: Annotated[
        int, typer.Option("--min-projects", min=2)
    ] = 2,
    smell: Annotated[
        list[str] | None,
        typer.Option("--smell", help="Repeat to train selected smells only."),
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Train one binary classifier per smell with a project holdout test set."""
    try:
        dataset = load_training_dataset(dataset_file)
        selected = _parse_smells(smell, dataset.smells)
        config = TrainingConfig(
            models=_parse_models(models),
            test_size=test_size,
            seed=seed,
            threshold=threshold,
            min_samples=min_samples,
            min_projects=min_projects,
        )
        report = train_holdout(
            dataset,
            output,
            config,
            smell_types=selected,
            overwrite=overwrite,
        )
        _render_ml_train(report, title="M5 project-holdout training")
    except (CodeSmellError, ValueError) as exc:
        _render_ml_error(exc)
        raise typer.Exit(code=1) from exc


@ml_app.command("logo")
def ml_logo(
    dataset_file: Annotated[
        Path, typer.Argument(help="M5 training_features.csv.")
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output", "-o", help="Leave-one-project-out evaluation directory."
        ),
    ] = Path("logo_m5"),
    models: Annotated[
        str, typer.Option("--models", help="Comma-separated model names.")
    ] = "logistic,random_forest",
    seed: Annotated[int, typer.Option("--seed")] = 42,
    threshold: Annotated[
        float, typer.Option("--threshold", min=0.01, max=0.99)
    ] = 0.5,
    min_samples: Annotated[int, typer.Option("--min-samples", min=2)] = 10,
    min_projects: Annotated[int, typer.Option("--min-projects", min=2)] = 2,
    smell: Annotated[
        list[str] | None,
        typer.Option("--smell", help="Repeat to evaluate selected smells only."),
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Run leave-one-project-out cross-project evaluation."""
    try:
        dataset = load_training_dataset(dataset_file)
        selected = _parse_smells(smell, dataset.smells)
        config = TrainingConfig(
            models=_parse_models(models),
            seed=seed,
            threshold=threshold,
            min_samples=min_samples,
            min_projects=min_projects,
        )
        report = leave_one_project_out(
            dataset,
            output,
            config,
            smell_types=selected,
            overwrite=overwrite,
        )
        _render_ml_train(report, title="M5 leave-one-project-out evaluation")
    except (CodeSmellError, ValueError) as exc:
        _render_ml_error(exc)
        raise typer.Exit(code=1) from exc


@ml_app.command("predict")
def ml_predict(
    dataset_file: Annotated[
        Path, typer.Argument(help="M5 feature dataset with the model's smell rows.")
    ],
    model_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing model.joblib and model_card.json."
        ),
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Prediction CSV.")
    ] = Path("ml_predictions.csv"),
    threshold: Annotated[
        float | None, typer.Option("--threshold", min=0.01, max=0.99)
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Apply a saved M5 model after verifying its feature schema and hash."""
    try:
        if output.exists() and not overwrite:
            raise ValueError("output file already exists; use --overwrite")
        dataset = load_training_dataset(dataset_file)
        rows = predict_with_model(dataset, model_dir, threshold=threshold)
        write_ml_csv(
            output,
            (
                "task_id",
                "project_fingerprint",
                "entity_id",
                "smell_type",
                "prediction",
                "probability",
                "model",
            ),
            rows,
        )
        console.print(f"[green]wrote {len(rows)} predictions to {output}[/green]")
    except (CodeSmellError, ValueError) as exc:
        _render_ml_error(exc)
        raise typer.Exit(code=1) from exc


@model_app.command("bootstrap")
def model_bootstrap() -> None:
    """Bootstrap default trained M5 model artifacts."""
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.ml.bootstrap import bootstrap_default_models

    settings = _cli_settings()
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        sessions = create_session_factory(engine)
        with sessions() as session:
            models = bootstrap_default_models(session, settings)
            console.print(f"[green]bootstrapped {len(models)} model artifacts[/green]")
    finally:
        engine.dispose()


@model_app.command("register")
def model_register(
    model_dir: Annotated[
        Path, typer.Argument(help="Trusted M5 directory containing model.joblib and model_card.json.")
    ],
    name: Annotated[str | None, typer.Option("--name")] = None,
    disabled: Annotated[bool, typer.Option("--disabled")] = False,
) -> None:
    """Verify and copy a trusted M5 artifact into private M7 storage."""
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.explain import ModelRegistry

    settings = _cli_settings()
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        sessions = create_session_factory(engine)
        with sessions() as session:
            artifact = ModelRegistry(settings.api.storage_root).register(
                session, model_dir, name=name, enabled=not disabled
            )
            console.print_json(json.dumps({
                "id": artifact.id,
                "name": artifact.name,
                "smell_type": artifact.smell_type,
                "model_kind": artifact.model_kind,
                "enabled": artifact.enabled,
                "model_sha256": artifact.model_sha256,
            }, indent=2))
    except ValueError as exc:
        console.print(f"[red]model_registry_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@model_app.command("list")
def model_list() -> None:
    """List registered model artifacts."""
    from sqlalchemy import select
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import ModelArtifact

    settings = _cli_settings()
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        sessions = create_session_factory(engine)
        with sessions() as session:
            models = list(session.scalars(select(ModelArtifact).order_by(ModelArtifact.smell_type)))
        table = Table(title="Registered M7 models")
        table.add_column("id", style="cyan")
        table.add_column("name")
        table.add_column("smell")
        table.add_column("kind")
        table.add_column("enabled")
        for item in models:
            table.add_row(item.id, item.name, item.smell_type, item.model_kind, str(item.enabled))
        console.print(table)
    finally:
        engine.dispose()


@model_app.command("verify")
def model_verify(
    model_id: Annotated[str, typer.Argument(help="Registered model UUID.")],
) -> None:
    """Recheck the stored model card, schema and SHA-256."""
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import ModelArtifact
    from codesmell.explain import ModelRegistry

    settings = _cli_settings()
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        sessions = create_session_factory(engine)
        with sessions() as session:
            artifact = session.get(ModelArtifact, model_id)
            if artifact is None:
                raise ValueError("registered model was not found")
            data = ModelRegistry(settings.api.storage_root).verify(artifact)
            console.print(f"[green]verified {artifact.name}: {data.sha256}[/green]")
    except ValueError as exc:
        console.print(f"[red]model_registry_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@model_app.command("set-enabled")
def model_set_enabled(
    model_id: Annotated[str, typer.Argument(help="Registered model UUID.")],
    enabled: Annotated[bool, typer.Option("--enabled/--disabled")]=True,
) -> None:
    """Enable or disable a registered model for new jobs."""
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import ModelArtifact

    settings = _cli_settings()
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        sessions = create_session_factory(engine)
        with sessions() as session:
            artifact = session.get(ModelArtifact, model_id)
            if artifact is None:
                raise ValueError("registered model was not found")
            artifact.enabled = enabled
            session.commit()
            console.print(f"[green]{artifact.name} enabled={enabled}[/green]")
    except ValueError as exc:
        console.print(f"[red]model_registry_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@user_app.command("create")
def user_create(
    email: Annotated[str, typer.Argument()],
    display_name: Annotated[str, typer.Option("--name")],
    role: Annotated[str, typer.Option("--role")] = "viewer",
    password: Annotated[str | None, typer.Option("--password", hide_input=True)] = None,
) -> None:
    """Create an administrator, analyst or viewer."""
    import getpass
    from codesmell.auth.service import create_user
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database

    if role not in {"admin", "analyst", "viewer"}:
        raise typer.BadParameter("role must be admin, analyst or viewer")
    secret = password or getpass.getpass("Password: ")
    settings = _cli_settings()
    upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            user = create_user(session, email=email, display_name=display_name, password=secret, role=role)  # type: ignore[arg-type]
            console.print(f"[green]created {user.role} {user.email} ({user.id})[/green]")
    except ValueError as exc:
        console.print(f"[red]user_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@user_app.command("list")
def user_list() -> None:
    """List platform users."""
    from sqlalchemy import select
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import User

    settings = _cli_settings(); upgrade_database(settings); engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            users = list(session.scalars(select(User).order_by(User.email)))
        table = Table(title="CodeSmell users")
        for column in ("id", "email", "name", "role", "enabled"):
            table.add_column(column)
        for user in users:
            table.add_row(user.id, user.email, user.display_name, user.role, str(user.enabled))
        console.print(table)
    finally:
        engine.dispose()


@user_app.command("set-password")
def user_set_password(
    email: Annotated[str, typer.Argument()],
    password: Annotated[str | None, typer.Option("--password", hide_input=True)] = None,
) -> None:
    """Reset a user's password."""
    import getpass
    from sqlalchemy import func, select
    from codesmell.auth.service import normalize_email, set_password
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import User

    secret = password or getpass.getpass("New password: ")
    settings = _cli_settings(); upgrade_database(settings); engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            user = session.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))
            if user is None:
                raise ValueError("user not found")
            set_password(session, user, secret)
            console.print(f"[green]password updated for {user.email}[/green]")
    except ValueError as exc:
        console.print(f"[red]user_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@user_app.command("set-enabled")
def user_set_enabled(
    email: Annotated[str, typer.Argument()],
    enabled: Annotated[bool, typer.Option("--enabled/--disabled")] = True,
) -> None:
    """Enable or disable a platform user."""
    from sqlalchemy import func, select
    from codesmell.auth.service import normalize_email
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import User

    settings = _cli_settings(); upgrade_database(settings); engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            user = session.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))
            if user is None:
                raise ValueError("user not found")
            user.enabled = enabled; session.commit()
            console.print(f"[green]{user.email} enabled={enabled}[/green]")
    except ValueError as exc:
        console.print(f"[red]user_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@report_app.command("generate")
def report_generate(
    job_id: Annotated[str, typer.Argument()],
    format: Annotated[str, typer.Option("--format")] = "pdf",
    title: Annotated[str | None, typer.Option("--title")] = None,
) -> None:
    """Generate and persist a JSON, CSV, HTML or PDF analysis report."""
    from datetime import UTC, datetime
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.db.models import GeneratedReport
    from codesmell.reports import generate_report

    if format not in {"json", "csv", "html", "pdf"}:
        raise typer.BadParameter("format must be json, csv, html or pdf")
    settings = _cli_settings(); upgrade_database(settings); engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            report = GeneratedReport(job_id=job_id, format=format, status="generating", title=title or f"CodeSmell Analysis Report - {job_id[:8]}")
            session.add(report); session.commit(); session.refresh(report)
            artifact = generate_report(session, settings, report)
            report.status="ready"; report.stored_path=str(artifact.path); report.filename=artifact.filename; report.media_type=artifact.media_type; report.size_bytes=artifact.size_bytes; report.content_sha256=artifact.sha256; report.completed_at=datetime.now(UTC)
            session.commit()
            console.print(f"[green]wrote {artifact.path} ({artifact.sha256})[/green]")
    except ValueError as exc:
        console.print(f"[red]report_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@research_app.command("summarize")
def research_summarize(
    holdout: Annotated[Path, typer.Argument(help="M5 holdout_report.json")],
    logo: Annotated[Path, typer.Argument(help="M5 logo_report.json")],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("research_m9"),
) -> None:
    """Create tables, figures and a publication-oriented research summary."""
    from codesmell.research import build_research_bundle

    try:
        summary = build_research_bundle(holdout, logo, output)
        console.print(f"[green]research bundle written to {output.resolve()}[/green]")
        console.print(f"LOGO folds evaluated: {summary.get('evaluated_logo_folds')}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        console.print(f"[red]research_error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Option("--revision")] = "head",
) -> None:
    """Apply packaged Alembic migrations."""
    from codesmell.db.migrate import upgrade_database

    settings = _cli_settings()
    upgrade_database(settings, revision)
    console.print(f"[green]database upgraded to {revision}[/green]")


@db_app.command("downgrade")
def db_downgrade(
    revision: Annotated[str, typer.Argument(help="Target Alembic revision.")],
) -> None:
    """Downgrade the database to a specific revision."""
    from codesmell.db.migrate import downgrade_database

    settings = _cli_settings()
    downgrade_database(settings, revision)
    console.print(f"[yellow]database downgraded to {revision}[/yellow]")


@api_app.command("serve")
def api_serve(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Run the FastAPI service with Uvicorn."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "codesmell.api.app:app",
        host=host or settings.api.host,
        port=port or settings.api.port,
        reload=reload,
        log_level=settings.logging.level.lower(),
    )


@worker_app.command("run")
def worker_run(
    once: Annotated[
        bool, typer.Option("--once", help="Process at most one job.")
    ] = False,
    worker_id: Annotated[str | None, typer.Option("--worker-id")] = None,
    migrate: Annotated[
        bool, typer.Option("--migrate/--no-migrate")
    ] = True,
) -> None:
    """Claim and execute queued analyses in a separate process."""
    from codesmell.db import create_db_engine, create_session_factory
    from codesmell.db.migrate import upgrade_database
    from codesmell.jobs import AnalysisWorker

    settings = _cli_settings()
    if migrate:
        upgrade_database(settings)
    engine = create_db_engine(settings)
    try:
        sessions = create_session_factory(engine)
        worker = AnalysisWorker(settings, sessions, worker_id=worker_id)
        if once:
            job_id = worker.run_once()
            if job_id is None:
                console.print("[yellow]no queued jobs[/yellow]")
            else:
                console.print(f"[green]processed job {job_id}[/green]")
            return
        console.print(f"worker {worker.worker_id} is polling for jobs")
        worker.run_forever()
    finally:
        engine.dispose()


def _parse_models(value: str) -> tuple[ModelKind, ...]:
    raw = [item.strip().lower() for item in value.split(",") if item.strip()]
    try:
        parsed = tuple(ModelKind(item) for item in raw)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ModelKind)
        raise ValueError(f"unknown model; expected one of {allowed}") from exc
    if not parsed:
        raise ValueError("at least one model is required")
    return tuple(dict.fromkeys(parsed))


def _parse_smells(
    requested: list[str] | None, available: tuple[str, ...]
) -> tuple[str, ...] | None:
    if not requested:
        return None
    normalized = tuple(dict.fromkeys(item.strip().lower() for item in requested))
    unknown = sorted(set(normalized) - set(available))
    if unknown:
        raise ValueError(
            f"smells are absent from this dataset: {', '.join(unknown)}"
        )
    return normalized


def _render_ml_prepare(payload: dict[str, Any]) -> None:
    table = Table(title="M5 feature dataset prepared", show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    for key in ("training_file", "rows", "projects", "training_sha256"):
        table.add_row(key.replace("_", " ").title(), str(payload[key]))
    console.print(table)


def _render_ml_split(payload: dict[str, Any]) -> None:
    created = sum(item["status"] == "created" for item in payload["splits"])
    skipped = sum(item["status"] == "skipped" for item in payload["splits"])
    table = Table(title="M5 project split", show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    table.add_row("Output", str(payload["output"]))
    table.add_row("Created", str(created))
    table.add_row("Skipped", str(skipped))
    console.print(table)


def _render_ml_train(payload: dict[str, Any], *, title: str) -> None:
    table = Table(title=title, show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    if payload.get("mode") == "project_holdout":
        table.add_row("Trained models", str(payload["trained_models"]))
        table.add_row("Skipped", str(payload["skipped"]))
    else:
        table.add_row("Evaluated folds", str(payload["evaluated_folds"]))
        table.add_row("Skipped folds", str(payload["skipped_folds"]))
    console.print(table)


def _render_ml_error(exc: Exception) -> None:
    if isinstance(exc, CodeSmellError):
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        if exc.details:
            console.print_json(json.dumps(exc.details, default=str, indent=2))
    else:
        console.print(f"[red]ml_error:[/red] {exc}")


def _render_dataset_build(payload: dict[str, Any]) -> None:
    table = Table(title="M4 dataset created", show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    for key in (
        "output_dir",
        "projects",
        "review_tasks",
        "rule_candidates",
        "sampled_controls",
        "snippets",
    ):
        table.add_row(key.replace("_", " ").title(), str(payload[key]))
    console.print(table)


def _render_validation(payload: dict[str, Any]) -> None:
    table = Table(title="Review validation", show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    for key in (
        "rows",
        "labelled",
        "unlabelled",
        "present",
        "absent",
        "uncertain",
        "valid",
        "complete",
    ):
        table.add_row(key.replace("_", " ").title(), str(payload[key]))
    table.add_row("Issues", str(len(payload["issues"])))
    console.print(table)


def _cli_settings() -> Settings:
    """Human-readable logs for interactive use; JSON stays the server default."""
    settings = get_settings()
    return settings.model_copy(
        update={"logging": settings.logging.model_copy(update={"json_output": False})}
    )


def _render(
    inventory: ProjectInventory, *, limit: int, rejections: bool
) -> None:
    summary = Table(title=f"Project: {inventory.name}", show_header=False)
    summary.add_column("field", style="cyan")
    summary.add_column("value")

    summary.add_row("Source", inventory.source_kind.value)
    summary.add_row("Origin", inventory.origin or "-")
    summary.add_row("Primary language", inventory.primary_language.value)
    summary.add_row(
        "Languages",
        ", ".join(
            f"{lang.value}={count}"
            for lang, count in sorted(
                inventory.languages.items(), key=lambda kv: kv[0].value
            )
        )
        or "-",
    )
    summary.add_row(
        "Build tools", ", ".join(b.value for b in inventory.build_tools) or "-"
    )
    summary.add_row("Files", f"{inventory.file_count:,}")
    summary.add_row("Lines", f"{inventory.total_lines:,}")
    summary.add_row("Bytes", f"{inventory.total_bytes:,}")
    summary.add_row("Dependencies", f"{len(inventory.dependencies):,}")
    summary.add_row("Rejected", f"{len(inventory.rejections):,}")
    summary.add_row("Fingerprint", inventory.fingerprint[:16])
    console.print(summary)

    files = Table(title=f"Largest source files (top {limit})")
    files.add_column("path", style="green", overflow="fold")
    files.add_column("lang")
    files.add_column("lines", justify="right")
    files.add_column("bytes", justify="right")

    largest = sorted(
        inventory.source_files, key=lambda f: f.line_count, reverse=True
    )[:limit]
    for source_file in largest:
        files.add_row(
            source_file.relative_path,
            source_file.language.value,
            f"{source_file.line_count:,}",
            f"{source_file.size_bytes:,}",
        )
    console.print(files)

    if rejections and inventory.rejections:
        refused = Table(title="Refused files")
        refused.add_column("path", style="red", overflow="fold")
        refused.add_column("reason")
        refused.add_column("detail")
        for rejection in inventory.rejections[:200]:
            refused.add_row(
                rejection.path, rejection.reason.value, rejection.detail or "-"
            )
        console.print(refused)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        console.print("[yellow]interrupted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
