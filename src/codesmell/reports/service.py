"""Deterministic JSON, CSV, HTML and PDF analysis reports for M9."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from codesmell.config.settings import Settings
from codesmell.db.models import (
    AnalysisJob,
    EntityMetricRecord,
    FindingRecord,
    GeneratedReport,
    MLPredictionRecord,
    ModelArtifact,
    PredictionExplanation,
    Project,
    RecommendationRecord,
)


@dataclass(frozen=True)
class ReportArtifact:
    path: Path
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned[:80] or "analysis"


def _rows(session: Session, model: type, predicate: object) -> list[Any]:
    return list(session.scalars(select(model).where(predicate)))


def build_payload(session: Session, job_id: str, max_rows: int) -> dict[str, Any]:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise ValueError("analysis not found")
    if job.status != "succeeded":
        raise ValueError("reports can only be generated for succeeded analyses")
    project = session.get(Project, job.project_id)
    if project is None:
        raise ValueError("project not found")

    findings = _rows(session, FindingRecord, FindingRecord.job_id == job_id)[:max_rows]
    metrics = _rows(session, EntityMetricRecord, EntityMetricRecord.job_id == job_id)[:max_rows]
    predictions = _rows(session, MLPredictionRecord, MLPredictionRecord.job_id == job_id)[:max_rows]
    recommendations = _rows(session, RecommendationRecord, RecommendationRecord.job_id == job_id)[:max_rows]
    prediction_ids = [item.id for item in predictions]
    explanations = (
        list(
            session.scalars(
                select(PredictionExplanation).where(
                    PredictionExplanation.prediction_id.in_(prediction_ids)
                )
            )
        )
        if prediction_ids
        else []
    )
    model_ids = sorted({item.model_id for item in predictions})
    models = (
        list(session.scalars(select(ModelArtifact).where(ModelArtifact.id.in_(model_ids))))
        if model_ids
        else []
    )

    def dump(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
        return {name: getattr(obj, name) for name in fields}

    payload: dict[str, Any] = {
        "schema_version": "m9-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "project": dump(
            project,
            (
                "id",
                "name",
                "source_type",
                "source_url",
                "original_filename",
                "content_sha256",
                "fingerprint",
                "status",
                "inventory_summary",
                "created_at",
                "updated_at",
            ),
        ),
        "analysis": dump(
            job,
            (
                "id",
                "status",
                "analysis_kind",
                "threshold_mode",
                "min_severity",
                "queued_at",
                "started_at",
                "completed_at",
                "summary",
                "model_ids",
                "explain_predictions",
            ),
        ),
        "models": [
            dump(
                item,
                (
                    "id",
                    "name",
                    "smell_type",
                    "entity_type",
                    "model_kind",
                    "model_sha256",
                    "threshold",
                    "feature_names",
                ),
            )
            for item in models
        ],
        "findings": [
            dump(
                item,
                (
                    "id",
                    "entity_id",
                    "smell_type",
                    "severity",
                    "confidence",
                    "detector",
                    "qualified_name",
                    "entity_type",
                    "relative_path",
                    "start_line",
                    "end_line",
                    "threshold_mode",
                    "rationale",
                    "evidence",
                    "references",
                ),
            )
            for item in findings
        ],
        "metrics": [
            dump(
                item,
                (
                    "id",
                    "entity_id",
                    "entity_type",
                    "qualified_name",
                    "relative_path",
                    "start_line",
                    "end_line",
                    "language",
                    "metrics",
                ),
            )
            for item in metrics
        ],
        "predictions": [
            dump(
                item,
                (
                    "id",
                    "model_id",
                    "entity_id",
                    "smell_type",
                    "prediction",
                    "probability",
                    "threshold",
                    "confidence",
                    "uncertainty",
                    "qualified_name",
                    "entity_type",
                    "relative_path",
                    "start_line",
                    "end_line",
                    "created_at",
                ),
            )
            for item in predictions
        ],
        "explanations": [
            dump(
                item,
                (
                    "id",
                    "prediction_id",
                    "method",
                    "base_value",
                    "output_value",
                    "top_features",
                    "warning",
                    "created_at",
                ),
            )
            for item in explanations
        ],
        "recommendations": [
            dump(
                item,
                (
                    "id",
                    "prediction_id",
                    "entity_id",
                    "smell_type",
                    "priority",
                    "title",
                    "summary",
                    "actions",
                    "evidence",
                    "validation_steps",
                    "created_at",
                ),
            )
            for item in recommendations
        ],
        "truncation": {
            "max_rows_per_section": max_rows,
            "findings_truncated": len(findings) == max_rows,
            "metrics_truncated": len(metrics) == max_rows,
            "predictions_truncated": len(predictions) == max_rows,
            "recommendations_truncated": len(recommendations) == max_rows,
        },
    }
    return payload


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _flatten(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "'" + value if value.startswith(("=", "+", "-", "@")) else value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, sort_keys=True, default=_json_default)


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    if rows:
        fieldnames = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _flatten(row.get(key)) for key in fieldnames})
    return stream.getvalue().encode("utf-8")


def _write_csv_bundle(payload: dict[str, Any], path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.csv", _csv_bytes([payload["project"]]))
        archive.writestr("analysis.csv", _csv_bytes([payload["analysis"]]))
        for section in (
            "models",
            "findings",
            "metrics",
            "predictions",
            "explanations",
            "recommendations",
        ):
            archive.writestr(f"{section}.csv", _csv_bytes(payload[section]))
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": payload["schema_version"],
                    "generated_at": payload["generated_at"],
                    "truncation": payload["truncation"],
                },
                indent=2,
            ),
        )


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key, "unknown"))
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _write_html(payload: dict[str, Any], path: Path, title: str) -> None:
    findings = payload["findings"]
    predictions = payload["predictions"]
    severity = _count_by(findings, "severity")
    smells = _count_by(findings, "smell_type")
    positive = sum(1 for row in predictions if row["prediction"])

    def esc(value: object) -> str:
        return html.escape(_flatten(value))

    def table(rows: list[dict[str, Any]], columns: tuple[str, ...], limit: int = 200) -> str:
        head = "".join(f"<th>{esc(c.replace('_', ' ').title())}</th>" for c in columns)
        body = []
        for row in rows[:limit]:
            body.append("<tr>" + "".join(f"<td>{esc(row.get(c))}</td>" for c in columns) + "</tr>")
        return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"

    summary_cards = [
        ("Files", (payload["project"].get("inventory_summary") or {}).get("file_count", 0)),
        ("Rule findings", len(findings)),
        ("ML predictions", len(predictions)),
        ("Positive ML", positive),
        ("Recommendations", len(payload["recommendations"])),
    ]
    cards = "".join(f"<div class='card'><span>{esc(k)}</span><strong>{esc(v)}</strong></div>" for k, v in summary_cards)
    severity_rows = [{"severity": k, "count": v} for k, v in severity.items()]
    smell_rows = [{"smell": k, "count": v} for k, v in smells.items()]
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>
body{{font-family:Inter,Arial,sans-serif;margin:0;background:#f6f8fb;color:#172033}}main{{max-width:1200px;margin:auto;padding:36px}}h1{{margin-bottom:4px}}.muted{{color:#64748b}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}}.card{{background:white;border:1px solid #dfe5ee;border-radius:12px;padding:16px}}.card span{{display:block;color:#64748b;font-size:13px}}.card strong{{font-size:28px}}section{{background:white;border:1px solid #dfe5ee;border-radius:14px;padding:20px;margin:18px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #e5eaf1;padding:8px;text-align:left;vertical-align:top}}th{{background:#f8fafc;position:sticky;top:0}}.table-wrap{{overflow:auto;max-height:620px}}code{{font-family:ui-monospace,monospace}}@media print{{body{{background:white}}main{{padding:0}}section{{break-inside:avoid}}}}
</style></head><body><main>
<h1>{esc(title)}</h1><p class="muted">Generated {esc(payload['generated_at'])} · Project {esc(payload['project']['name'])} · Analysis {esc(payload['analysis']['id'])}</p>
<div class="cards">{cards}</div>
<section><h2>Analysis configuration</h2>{table([payload['analysis']], ('analysis_kind','threshold_mode','min_severity','status','started_at','completed_at'))}</section>
<section><h2>Severity distribution</h2>{table(severity_rows, ('severity','count'))}</section>
<section><h2>Code-smell distribution</h2>{table(smell_rows, ('smell','count'))}</section>
<section><h2>Rule findings</h2>{table(findings, ('severity','smell_type','qualified_name','relative_path','start_line','confidence','rationale'))}</section>
<section><h2>ML predictions</h2>{table(predictions, ('prediction','smell_type','probability','confidence','uncertainty','qualified_name','relative_path','start_line'))}</section>
<section><h2>Recommendations</h2>{table(payload['recommendations'], ('priority','smell_type','title','summary','actions','validation_steps'))}</section>
<footer class="muted">CodeSmell M9 report schema {esc(payload['schema_version'])}. Source code is analyzed statically and is never executed.</footer>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def _write_pdf(payload: dict[str, Any], path: Path, title: str, settings: Settings) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="CodeSmell",
    )
    story: list[Any] = [
        Paragraph(html.escape(title), styles["CenterTitle"]),
        Paragraph(
            html.escape(
                f"Project: {payload['project']['name']} | Analysis: {payload['analysis']['id']} | Generated: {payload['generated_at']}"
            ),
            styles["Small"],
        ),
        Spacer(1, 8),
    ]
    summary = [
        ["Measure", "Value"],
        ["Analysis kind", payload["analysis"]["analysis_kind"]],
        ["Rule findings", str(len(payload["findings"]))],
        ["ML predictions", str(len(payload["predictions"]))],
        ["Positive predictions", str(sum(1 for row in payload["predictions"] if row["prediction"]))],
        ["Recommendations", str(len(payload["recommendations"]))],
    ]
    t = Table(summary, colWidths=[62 * mm, 105 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8eef8")), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#b8c2d1")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8), ("PADDING", (0,0), (-1,-1), 5)]))
    story.extend([t, Spacer(1, 12), Paragraph("Finding distribution", styles["Heading2"])])
    distribution = [["Smell", "Count"]] + [[k, str(v)] for k, v in _count_by(payload["findings"], "smell_type").items()]
    dt = Table(distribution or [["Smell","Count"]], colWidths=[125 * mm, 35 * mm])
    dt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8eef8")), ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#cbd5e1")), ("FONTSIZE", (0,0), (-1,-1), 8), ("PADDING", (0,0), (-1,-1), 4)]))
    story.extend([dt, PageBreak(), Paragraph("Rule-based findings", styles["Heading1"])])
    for item in payload["findings"][: settings.reports.pdf_max_findings]:
        heading = f"{item['severity'].upper()} - {item['smell_type']} - {item['qualified_name']}"
        story.append(Paragraph(html.escape(heading), styles["Heading3"]))
        story.append(Paragraph(html.escape(f"{item['relative_path']}:{item['start_line']}-{item['end_line']} | confidence {item['confidence']:.3f}"), styles["Small"]))
        story.append(Paragraph(html.escape(item.get("rationale") or "No rationale recorded."), styles["BodyText"]))
        story.append(Spacer(1, 6))
    if payload["predictions"]:
        story.extend([PageBreak(), Paragraph("Machine-learning predictions", styles["Heading1"])])
        for item in payload["predictions"][: settings.reports.pdf_max_predictions]:
            label = "PRESENT" if item["prediction"] else "ABSENT"
            story.append(Paragraph(html.escape(f"{label} - {item['smell_type']} - {item['qualified_name']}"), styles["Heading3"]))
            story.append(Paragraph(html.escape(f"Probability {item['probability']:.3f}; confidence {item['confidence']:.3f}; uncertainty {item['uncertainty']:.3f}; {item['relative_path']}:{item['start_line']}"), styles["Small"]))
            story.append(Spacer(1, 5))
    if payload["recommendations"]:
        story.extend([PageBreak(), Paragraph("Refactoring recommendations", styles["Heading1"])])
        for item in payload["recommendations"]:
            story.append(Paragraph(html.escape(f"{item['priority'].upper()} - {item['title']}"), styles["Heading3"]))
            story.append(Paragraph(html.escape(item["summary"]), styles["BodyText"]))
            actions = "<br/>".join(f"- {html.escape(str(action))}" for action in item["actions"])
            story.append(Paragraph(actions, styles["BodyText"]))
            story.append(Spacer(1, 7))
    doc.build(story)


def generate_report(
    session: Session,
    settings: Settings,
    report: GeneratedReport,
) -> ReportArtifact:
    payload = build_payload(session, report.job_id, settings.reports.max_rows_per_section)
    project_name = str(payload["project"]["name"])
    basename = f"{_safe_slug(project_name)}-{report.job_id[:8]}-{report.format}"
    root = (settings.api.storage_root / "reports" / report.id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if report.format == "json":
        filename, media_type = f"{basename}.json", "application/json"
        path = root / filename
        _write_json(payload, path)
    elif report.format == "csv":
        filename, media_type = f"{basename}-csv.zip", "application/zip"
        path = root / filename
        _write_csv_bundle(payload, path)
    elif report.format == "html":
        filename, media_type = f"{basename}.html", "text/html; charset=utf-8"
        path = root / filename
        _write_html(payload, path, report.title)
    elif report.format == "pdf":
        filename, media_type = f"{basename}.pdf", "application/pdf"
        path = root / filename
        _write_pdf(payload, path, report.title, settings)
    else:
        raise ValueError(f"unsupported report format: {report.format}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ReportArtifact(
        path=path,
        filename=filename,
        media_type=media_type,
        size_bytes=path.stat().st_size,
        sha256=digest,
    )
