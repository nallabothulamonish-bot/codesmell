"""Background analysis execution and result persistence."""

from __future__ import annotations

import shutil
import socket
import time
import uuid

import joblib
from threading import Event, Thread
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from codesmell.config.logging import get_logger
from codesmell.config.settings import Settings
from codesmell.container import build_container
from codesmell.core.enums import Severity, SmellType
from codesmell.core.errors import CodeSmellError
from codesmell.db.models import (
    AnalysisJob,
    EntityMetricRecord,
    FindingRecord,
    JobEvent,
    MLPredictionRecord,
    ModelArtifact,
    PredictionExplanation,
    Project,
    RecommendationRecord,
    SourceFileRecord,
)
from codesmell.detectors import ThresholdMode
from codesmell.explain import ModelRegistry, build_recommendation, explain_predictions
from codesmell.ml.evaluation import probability_of_positive
from codesmell.ml.models import FEATURE_PREFIX
from codesmell.jobs.queue import claim_next_job, recover_stale_jobs

logger = get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


class JobCancelled(RuntimeError):
    pass


class AnalysisWorker:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = session_factory
        self.worker_id = worker_id or default_worker_id()
        self.container = build_container(settings)

    def run_once(self) -> str | None:
        with self.sessions() as session:
            recover_stale_jobs(session, self.settings.worker.stale_after_seconds)
            job = claim_next_job(session, self.worker_id)
        if job is None:
            return None
        self.process(job.id)
        return job.id

    def run_forever(self, *, stop: Callable[[], bool] | None = None) -> None:
        should_stop = stop or (lambda: False)
        while not should_stop():
            claimed = self.run_once()
            if claimed is None:
                time.sleep(self.settings.worker.poll_interval_seconds)

    def process(self, job_id: str) -> None:
        heartbeat_stop = Event()
        heartbeat = Thread(
            target=self._heartbeat_loop,
            args=(job_id, heartbeat_stop),
            daemon=True,
            name=f"codesmell-heartbeat-{job_id[:8]}",
        )
        heartbeat.start()
        try:
            self._run_pipeline(job_id)
        except JobCancelled:
            self._mark_cancelled(job_id)
        except CodeSmellError as exc:
            self._mark_failed(job_id, exc.code, exc.message)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            logger.exception("analysis job failed", extra={"job_id": job_id})
            self._mark_failed(job_id, type(exc).__name__, str(exc))
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2.0)

    def _heartbeat_loop(self, job_id: str, stop: Event) -> None:
        interval = self.settings.worker.heartbeat_interval_seconds
        while not stop.wait(interval):
            with self.sessions() as session:
                job = session.get(AnalysisJob, job_id)
                if (
                    job is None
                    or job.status != "running"
                    or job.locked_by != self.worker_id
                ):
                    return
                job.heartbeat_at = utcnow()
                session.commit()

    def _run_pipeline(self, job_id: str) -> None:
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is None:
                return
            job.error_code = None
            job.error_message = None
            project = session.get(Project, job.project_id)
            if project is None:
                raise RuntimeError("job project no longer exists")
            try:
                threshold_mode = ThresholdMode(job.threshold_mode)
            except ValueError:
                if "percentile" in str(job.threshold_mode).lower() or "relative" in str(job.threshold_mode).lower():
                    threshold_mode = ThresholdMode.PERCENTILE
                else:
                    threshold_mode = ThresholdMode.ABSOLUTE
            severity_floor = Severity(job.min_severity)
            analysis_kind = job.analysis_kind
            requested_model_ids = list(job.model_ids or [])
            should_explain = job.explain_predictions
            session.commit()

        self._progress(job_id, 5, "creating isolated workspace")
        self._check_cancel(job_id)
        with self.container.workspaces.session(job_id=job_id) as workspace:
            with self.sessions() as session:
                job = session.get(AnalysisJob, job_id)
                if job is None:
                    return
                project = session.get(Project, job.project_id)
                if project is None:
                    raise RuntimeError("job project no longer exists")
                source = self._materialize_source(project, workspace)
            self._progress(job_id, 15, f"fetching source files for {project.name}")
            def on_progress(pct: int, msg: str) -> None:
                scaled_pct = 5 + int((pct / 100.0) * 25)
                self._progress(job_id, scaled_pct, msg)

            ingested = self.container.ingestion_service(workspace).ingest(
                source, progress_callback=on_progress
            )
            self._persist_inventory(job_id, ingested.inventory)
            self._progress(job_id, 35, f"ingested {len(ingested.inventory.source_files)} source files")
            self._check_cancel(job_id)

            analysis = self.container.metrics_engine().analyze(
                ingested.root, ingested.inventory
            )
            self._persist_metrics(job_id, analysis)
            self._progress(job_id, 70, "software metrics calculated")
            self._check_cancel(job_id)

            detection_summary: dict[str, object] | None = None
            if analysis_kind in {"rule", "hybrid"}:
                report = self.container.detection_engine(threshold_mode).detect(analysis)
                stored_findings = self._persist_findings(
                    job_id, report, severity_floor
                )
                detection_summary = {
                    **report.summary(),
                    "stored_findings": stored_findings,
                    "minimum_severity": severity_floor.value,
                }
            else:
                self._clear_findings(job_id)
            self._progress(job_id, 78, "rule analysis completed")
            self._check_cancel(job_id)

            ml_summary: dict[str, object] | None = None
            if analysis_kind in {"ml", "hybrid"}:
                ml_summary = self._run_ml_models(
                    job_id,
                    analysis,
                    requested_model_ids=requested_model_ids,
                    should_explain=should_explain,
                )
            else:
                self._clear_ml_results(job_id)
            self._progress(job_id, 95, "predictions and explanations persisted")
            self._check_cancel(job_id)

            summary = {
                "analysis_kind": analysis_kind,
                "inventory": ingested.inventory.summary(),
                "analysis": analysis.summary(),
                "detection": detection_summary,
                "machine_learning": ml_summary,
                "warnings": list(ingested.warnings),
            }
            self._mark_succeeded(job_id, summary)

    @staticmethod
    def _materialize_source(project: Project, workspace: object) -> str:
        from codesmell.ingestion.sandbox import Workspace

        assert isinstance(workspace, Workspace)
        if project.source_type == "github":
            if not project.source_url:
                raise RuntimeError("GitHub project is missing source_url")
            return project.source_url
        if not project.stored_path:
            raise RuntimeError("uploaded project is missing stored_path")
        stored = Path(project.stored_path)
        if not stored.is_file():
            raise RuntimeError("stored upload is no longer available")
        original = Path(project.original_filename or stored.name).name
        staged = workspace.resolve_within(workspace.upload_dir, original)
        shutil.copyfile(stored, staged)
        return str(staged)

    def _persist_inventory(self, job_id: str, inventory: object) -> None:
        from codesmell.core.models import ProjectInventory

        assert isinstance(inventory, ProjectInventory)
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is None:
                return
            project = session.get(Project, job.project_id)
            if project is None:
                return
            session.execute(
                delete(SourceFileRecord).where(SourceFileRecord.project_id == project.id)
            )
            project.fingerprint = inventory.fingerprint
            project.status = "analyzed"
            project.inventory_summary = inventory.summary()
            for source_file in inventory.source_files:
                session.add(
                    SourceFileRecord(
                        project_id=project.id,
                        relative_path=source_file.relative_path,
                        language=source_file.language.value,
                        size_bytes=source_file.size_bytes,
                        line_count=source_file.line_count,
                        sha256=source_file.sha256,
                    )
                )
            session.commit()

    def _persist_metrics(self, job_id: str, analysis: object) -> None:
        from codesmell.metrics.engine import AnalysisResult

        assert isinstance(analysis, AnalysisResult)
        with self.sessions() as session:
            session.execute(
                delete(EntityMetricRecord).where(EntityMetricRecord.job_id == job_id)
            )
            for entity_id, vector in analysis.features.items():
                entity = analysis.context.entity_by_id(entity_id)
                if entity is None:
                    continue
                session.add(
                    EntityMetricRecord(
                        job_id=job_id,
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type.value,
                        qualified_name=entity.qualified_name,
                        relative_path=entity.relative_path,
                        start_line=entity.start_line,
                        end_line=entity.end_line,
                        language=entity.language.value,
                        metrics=dict(vector.values),
                    )
                )
            session.commit()

    def _persist_findings(
        self, job_id: str, report: object, floor: Severity
    ) -> int:
        from codesmell.detectors import DetectionReport

        assert isinstance(report, DetectionReport)
        stored = 0
        with self.sessions() as session:
            session.execute(
                delete(FindingRecord).where(FindingRecord.job_id == job_id)
            )
            for finding in report.findings:
                if finding.severity.rank < floor.rank:
                    continue
                payload = finding.to_dict()
                entity = payload["entity"]
                assert isinstance(entity, dict)
                conditions = payload["conditions"]
                assert isinstance(conditions, list)
                session.add(
                    FindingRecord(
                        job_id=job_id,
                        entity_id=finding.entity.entity_id,
                        smell_type=finding.smell_type.value,
                        severity=finding.severity.value,
                        confidence=finding.prediction.confidence,
                        detector=finding.prediction.model_name,
                        qualified_name=finding.entity.qualified_name,
                        entity_type=finding.entity.entity_type.value,
                        relative_path=finding.entity.relative_path,
                        start_line=finding.entity.start_line,
                        end_line=finding.entity.end_line,
                        threshold_mode=finding.threshold_mode.value,
                        rationale=finding.rationale,
                        evidence=conditions,
                        references=list(finding.references),
                    )
                )
                stored += 1
            session.commit()
        return stored

    def _clear_findings(self, job_id: str) -> None:
        with self.sessions() as session:
            session.execute(delete(FindingRecord).where(FindingRecord.job_id == job_id))
            session.commit()

    def _clear_ml_results(self, job_id: str) -> None:
        with self.sessions() as session:
            prediction_ids = list(
                session.scalars(
                    select(MLPredictionRecord.id).where(MLPredictionRecord.job_id == job_id)
                )
            )
            session.execute(
                delete(RecommendationRecord).where(RecommendationRecord.job_id == job_id)
            )
            if prediction_ids:
                session.execute(
                    delete(PredictionExplanation).where(
                        PredictionExplanation.prediction_id.in_(prediction_ids)
                    )
                )
            session.execute(
                delete(MLPredictionRecord).where(MLPredictionRecord.job_id == job_id)
            )
            session.commit()

    def _run_ml_models(
        self,
        job_id: str,
        analysis: object,
        *,
        requested_model_ids: list[str],
        should_explain: bool,
    ) -> dict[str, object]:
        from codesmell.metrics.engine import AnalysisResult

        assert isinstance(analysis, AnalysisResult)
        self._clear_ml_results(job_id)
        with self.sessions() as session:
            statement = select(ModelArtifact).where(ModelArtifact.enabled.is_(True))
            if requested_model_ids:
                statement = statement.where(ModelArtifact.id.in_(requested_model_ids))
            artifacts = list(session.scalars(statement.order_by(ModelArtifact.smell_type)))
        if not artifacts:
            raise RuntimeError("no enabled registered ML models are available")
        if requested_model_ids and {item.id for item in artifacts} != set(requested_model_ids):
            raise RuntimeError("one or more requested models are missing or disabled")

        registry = ModelRegistry(self.settings.api.storage_root)
        totals = {
            "models": len(artifacts),
            "predictions": 0,
            "positive_predictions": 0,
            "explanations": 0,
            "recommendations": 0,
            "by_smell": {},
            "model_ids": [item.id for item in artifacts],
        }
        by_smell: dict[str, dict[str, int]] = {}
        for idx, artifact in enumerate(artifacts):
            prog = 78 + int(15 * (idx + 1) / len(artifacts))
            self._progress(job_id, prog, f"evaluating ML model {artifact.smell_type}")
            data = registry.verify(artifact)
            model = joblib.load(data.model_path)
            smell = SmellType(artifact.smell_type)
            feature_names = tuple(artifact.feature_names)
            candidates: list[tuple[object, object, list[float]]] = []
            for entity_id, vector in analysis.features.items():
                entity = analysis.context.entity_by_id(entity_id)
                if entity is None or entity.entity_type is not smell.entity_type:
                    continue
                values: list[float] = []
                missing: list[str] = []
                for feature in feature_names:
                    metric = feature.removeprefix(FEATURE_PREFIX)
                    if metric not in vector.values:
                        missing.append(metric)
                    else:
                        values.append(float(vector.values[metric]))
                if missing:
                    raise RuntimeError(
                        f"model {artifact.id} requires unavailable metrics: {', '.join(missing)}"
                    )
                candidates.append((entity, vector, values))
            if not candidates:
                by_smell[artifact.smell_type] = {"predictions": 0, "positive": 0}
                continue

            value_matrix = [values for _entity, _vector, values in candidates]
            probabilities = probability_of_positive(model, value_matrix)
            explanations = (
                explain_predictions(
                    model,
                    feature_names,
                    value_matrix,
                    top_k=self.settings.explainability.top_features,
                    prefer_shap=self.settings.explainability.prefer_shap,
                )
                if should_explain
                else [None] * len(candidates)
            )
            smell_counts = {"predictions": 0, "positive": 0}
            with self.sessions() as session:
                for (entity, vector, values), probability, explanation in zip(
                    candidates, probabilities, explanations, strict=True
                ):
                    predicted = probability >= artifact.threshold
                    confidence = probability if predicted else 1.0 - probability
                    uncertainty = 1.0 - confidence
                    prediction = MLPredictionRecord(
                        job_id=job_id,
                        model_id=artifact.id,
                        entity_id=entity.entity_id,
                        smell_type=artifact.smell_type,
                        prediction=predicted,
                        probability=float(probability),
                        threshold=artifact.threshold,
                        confidence=float(confidence),
                        uncertainty=float(uncertainty),
                        qualified_name=entity.qualified_name,
                        entity_type=entity.entity_type.value,
                        relative_path=entity.relative_path,
                        start_line=entity.start_line,
                        end_line=entity.end_line,
                    )
                    session.add(prediction)
                    session.flush()
                    top_features: list[dict[str, object]] = []
                    if explanation is not None:
                        top_features = explanation.top_features
                        session.add(
                            PredictionExplanation(
                                prediction_id=prediction.id,
                                method=explanation.method,
                                base_value=explanation.base_value,
                                output_value=explanation.output_value,
                                top_features=top_features,
                                warning=explanation.warning,
                            )
                        )
                        totals["explanations"] = int(totals["explanations"]) + 1
                    should_recommend = (
                        predicted
                        or not self.settings.explainability.recommendations_for_positive_only
                    )
                    if should_recommend:
                        recommendation = build_recommendation(
                            artifact.smell_type,
                            dict(vector.values),
                            top_features,
                            probability=float(probability),
                        )
                        session.add(
                            RecommendationRecord(
                                job_id=job_id,
                                prediction_id=prediction.id,
                                entity_id=entity.entity_id,
                                smell_type=artifact.smell_type,
                                priority=str(recommendation["priority"]),
                                title=str(recommendation["title"]),
                                summary=str(recommendation["summary"]),
                                actions=list(recommendation["actions"]),
                                evidence=list(recommendation["evidence"]),
                                validation_steps=list(recommendation["validation_steps"]),
                            )
                        )
                        totals["recommendations"] = int(totals["recommendations"]) + 1
                    totals["predictions"] = int(totals["predictions"]) + 1
                    smell_counts["predictions"] += 1
                    if predicted:
                        totals["positive_predictions"] = int(totals["positive_predictions"]) + 1
                        smell_counts["positive"] += 1
                session.commit()
            by_smell[artifact.smell_type] = smell_counts
        totals["by_smell"] = by_smell
        return totals

    def _progress(self, job_id: str, progress: int, message: str) -> None:
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is None:
                return
            job.progress = progress
            job.progress_message = message
            job.heartbeat_at = utcnow()
            session.add(
                JobEvent(
                    job_id=job_id,
                    event_type="progress",
                    message=message,
                    details={"progress": progress},
                )
            )
            session.commit()

    def _check_cancel(self, job_id: str) -> None:
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is not None and job.cancel_requested:
                raise JobCancelled

    def _mark_succeeded(self, job_id: str, summary: dict[str, object]) -> None:
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.progress = 100
            job.progress_message = "analysis completed"
            job.completed_at = utcnow()
            job.heartbeat_at = utcnow()
            job.summary = summary
            job.locked_by = None
            job.locked_at = None
            session.add(JobEvent(job_id=job_id, event_type="succeeded", message="Analysis completed"))
            session.commit()

    def _mark_cancelled(self, job_id: str) -> None:
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is None:
                return
            job.status = "cancelled"
            job.progress_message = "analysis cancelled"
            job.completed_at = utcnow()
            job.locked_by = None
            job.locked_at = None
            session.add(JobEvent(job_id=job_id, event_type="cancelled", message="Analysis cancelled"))
            session.commit()

    def _mark_failed(self, job_id: str, code: str, message: str) -> None:
        with self.sessions() as session:
            job = session.get(AnalysisJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.progress_message = f"Analysis failed: {message[:120]}"
            job.completed_at = utcnow()
            job.error_code = code[:120]
            job.error_message = message[:4000]
            job.locked_by = None
            job.locked_at = None
            session.add(
                JobEvent(
                    job_id=job_id,
                    event_type="failed",
                    message="Analysis failed",
                    details={"error_code": code, "error_message": message[:1000]},
                )
            )
            session.commit()
