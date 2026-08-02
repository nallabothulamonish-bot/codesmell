"""Publication-oriented summaries for M5 holdout and LOGO reports."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

_METRICS = ("accuracy", "balanced_accuracy", "precision", "recall", "specificity", "f1", "mcc", "roc_auc", "pr_auc", "brier_score")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_research_bundle(holdout_path: Path, logo_path: Path, output: Path) -> dict[str, Any]:
    holdout = _load(holdout_path)
    logo = _load(logo_path)
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    figures.mkdir(exist_ok=True)

    holdout_rows: list[dict[str, Any]] = []
    for item in holdout.get("results", []):
        if item.get("status") != "trained":
            continue
        row = {"smell_type": item.get("smell_type"), "model": item.get("model"), "test_projects": ";".join(item.get("test_projects", [])), "support": item.get("metrics", {}).get("support")}
        row.update({metric: item.get("metrics", {}).get(metric) for metric in _METRICS})
        holdout_rows.append(row)

    fold_rows: list[dict[str, Any]] = []
    fold_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in logo.get("folds", []):
        if item.get("status") != "evaluated":
            continue
        row = {
            "smell_type": item.get("smell_type"),
            "model": item.get("model"),
            "held_out_project": item.get("held_out_project"),
            "test_rows": item.get("test_rows"),
        }
        row.update({metric: item.get("metrics", {}).get(metric) for metric in _METRICS})
        fold_rows.append(row)
        fold_groups.setdefault((str(row["smell_type"]), str(row["model"])), []).append(row)

    logo_rows: list[dict[str, Any]] = []
    for key, item in sorted(logo.get("aggregate", {}).items()):
        row = {"key": key, "smell_type": item.get("smell_type"), "model": item.get("model"), "folds": item.get("folds")}
        row.update({f"macro_{metric}": item.get("macro_mean", {}).get(metric) for metric in _METRICS})
        row.update({f"micro_{metric}": item.get("micro", {}).get(metric) for metric in _METRICS})
        group = fold_groups.get((str(item.get("smell_type")), str(item.get("model"))), [])
        for metric in _METRICS:
            values = [float(fold[metric]) for fold in group if fold.get(metric) is not None]
            deviation = statistics.stdev(values) if len(values) > 1 else 0.0 if values else None
            row[f"std_{metric}"] = deviation
            row[f"ci95_{metric}"] = (1.96 * deviation / math.sqrt(len(values))) if deviation is not None and values else None
        logo_rows.append(row)

    _write_csv(output / "holdout_metrics.csv", holdout_rows)
    _write_csv(output / "logo_fold_metrics.csv", fold_rows)
    _write_csv(output / "logo_metrics.csv", logo_rows)

    labels = [f"{row['smell_type']}\n{row['model']}" for row in logo_rows]
    for metric in ("f1", "mcc", "roc_auc", "pr_auc"):
        values = [row.get(f"macro_{metric}") for row in logo_rows]
        errors = [row.get(f"ci95_{metric}") for row in logo_rows]
        valid = [(label, float(value), float(error or 0.0)) for label, value, error in zip(labels, values, errors, strict=True) if value is not None]
        if not valid:
            continue
        fig, ax = plt.subplots(figsize=(max(6, len(valid) * 1.4), 4.5))
        ax.bar([item[0] for item in valid], [item[1] for item in valid], yerr=[item[2] for item in valid], capsize=4)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel(metric.replace("_", " ").upper())
        ax.set_title(f"LOGO macro {metric.replace('_', ' ')}")
        ax.tick_params(axis="x", rotation=25)
        fig.tight_layout()
        fig.savefig(figures / f"logo_macro_{metric}.png", dpi=180)
        plt.close(fig)

    summary = {
        "schema_version": "m9-research-v1",
        "holdout_source": str(holdout_path),
        "logo_source": str(logo_path),
        "holdout_results": holdout_rows,
        "logo_results": logo_rows,
        "logo_fold_results": fold_rows,
        "evaluated_logo_folds": logo.get("evaluated_folds"),
        "skipped_logo_folds": logo.get("skipped_folds", []),
        "warnings": [
            "Report project-level and LOGO results separately.",
            "Do not report synthetic demo metrics as research findings.",
            "Include confidence intervals or repeated seeds for final publication claims.",
        ],
    }
    (output / "research_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# CodeSmell Research Evaluation Summary",
        "",
        "## Leakage controls",
        "",
        "- Outer holdout partitions entire projects.",
        "- LOGO holds out one complete project per fold.",
        "- Hyperparameter selection remains inside training projects.",
        "",
        "## Holdout results",
        "",
        "| Smell | Model | F1 | MCC | ROC-AUC | PR-AUC |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in holdout_rows:
        lines.append(f"| {row['smell_type']} | {row['model']} | {row.get('f1', '')} | {row.get('mcc', '')} | {row.get('roc_auc', '')} | {row.get('pr_auc', '')} |")
    lines += ["", "## LOGO macro results", "", "| Smell | Model | Folds | F1 | MCC | ROC-AUC | PR-AUC |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in logo_rows:
        lines.append(f"| {row['smell_type']} | {row['model']} | {row.get('folds', '')} | {row.get('macro_f1', '')} +/- {row.get('ci95_f1', '')} | {row.get('macro_mcc', '')} +/- {row.get('ci95_mcc', '')} | {row.get('macro_roc_auc', '')} +/- {row.get('ci95_roc_auc', '')} | {row.get('macro_pr_auc', '')} +/- {row.get('ci95_pr_auc', '')} |")
    lines += ["", "## Reporting cautions", "", *[f"- {item}" for item in summary["warnings"]]]
    (output / "RESEARCH_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
