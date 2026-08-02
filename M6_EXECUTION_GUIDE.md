# CodeSmell M6 Execution Guide

M6 adds a FastAPI backend, SQLAlchemy database, Alembic migrations, safe upload
and GitHub project APIs, and a persistent database-backed analysis worker.
The API process does not perform heavy analysis itself: it creates a queued job,
and a separate worker claims and executes it.

## 1. Install

From the folder containing `pyproject.toml`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

Verify:

```powershell
codesmell version
```

Expected:

```text
codesmell 0.4.0
```

## 2. Local SQLite configuration

The default development database is SQLite. Copy `.env.example` to `.env`, or
use these defaults:

```text
CODESMELL_DATABASE__URL=sqlite:///./codesmell.db
CODESMELL_DATABASE__AUTO_MIGRATE=true
CODESMELL_API__STORAGE_ROOT=.codesmell-data
CODESMELL_WORKSPACE_ROOT=.codesmell-workspaces
```

Uploaded archives are stored under `.codesmell-data/uploads`. Extracted source
exists only inside a per-job workspace and is removed after the job finishes.

## 3. Apply database migrations

```powershell
codesmell db upgrade
```

M6 creates these tables:

```text
projects
analysis_jobs
source_files
entity_metrics
findings
job_events
alembic_version
```

In development, `database.auto_migrate=true` also applies pending migrations
when the API starts. Production mode refuses automatic migrations; run the
migration command explicitly during deployment.

## 4. Start the API

Open terminal 1:

```powershell
.venv\Scripts\Activate.ps1
codesmell api serve --host 127.0.0.1 --port 8000 --reload
```

Open in a browser:

```text
http://127.0.0.1:8000/docs
```

Health checks:

```text
http://127.0.0.1:8000/health/live
http://127.0.0.1:8000/health/ready
```

## 5. Start the background worker

Open terminal 2:

```powershell
.venv\Scripts\Activate.ps1
codesmell worker run
```

The worker continuously polls the database. To process at most one queued job:

```powershell
codesmell worker run --once
```

The queue supports:

- deterministic oldest-job-first claiming;
- conditional atomic claims so two workers do not execute the same queued job;
- worker heartbeat updates during long analysis;
- stale-worker recovery;
- configurable retry limits;
- queued and cooperative running-job cancellation;
- persistent job events and progress messages.

## 6. Upload a project

M6 accepts `.zip` and `.py` uploads. With `curl.exe` on Windows:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/projects/upload" `
  -F "file=@D:\Projects\student-management.zip" `
  -F "name=Student Management"
```

The response contains the project ID:

```json
{
  "id": "PROJECT_ID",
  "name": "Student Management",
  "source_type": "upload",
  "status": "registered"
}
```

The upload is streamed to disk while enforcing the configured byte limit. The
server creates its own storage filename and never trusts the submitted path.
ZIP structure is validated again by the hardened M1 extractor when the worker
runs.

## 7. Register a public GitHub repository

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/projects/github" `
  -H "Content-Type: application/json" `
  -d '{"url":"https://github.com/psf/requests","name":"Requests"}'
```

Only public HTTPS repositories on the configured host allowlist are accepted.
The default hosts are GitHub, GitLab and Bitbucket.

## 8. Queue an analysis

Replace `PROJECT_ID` with the returned project ID:

```powershell
curl.exe -X POST `
  "http://127.0.0.1:8000/api/v1/projects/PROJECT_ID/analyses" `
  -H "Content-Type: application/json" `
  -d '{"threshold_mode":"absolute","min_severity":"low","max_attempts":3}'
```

The API returns HTTP `202 Accepted` with a job ID. The available threshold modes
are `absolute` and `percentile`. The minimum persisted severity can be `low`,
`medium`, `high`, or `critical`.

## 9. Check job progress

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID"
```

Job states:

```text
queued -> running -> succeeded
                  -> failed -> queued (manual retry)
queued/running -> cancelled
```

Progress history:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/events"
```

Cancel a job:

```powershell
curl.exe -X POST `
  "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/cancel"
```

Retry a failed job when attempts remain:

```powershell
curl.exe -X POST `
  "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/retry"
```

## 10. Retrieve metrics and findings

Metrics:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/metrics?entity_type=method&limit=100"
```

Findings:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/findings?severity=high&limit=100"
```

Useful filters:

```text
Metrics:  entity_type, path, limit, offset
Findings: smell, severity, path, limit, offset
```

Each finding includes its source location, detector, confidence, threshold
mode, rationale, references and complete metric-condition evidence.

## 11. Main API endpoints

```text
GET    /health/live
GET    /health/ready
POST   /api/v1/projects/upload
POST   /api/v1/projects/github
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}
DELETE /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}/analyses
GET    /api/v1/analyses
GET    /api/v1/analyses/{job_id}
POST   /api/v1/analyses/{job_id}/cancel
POST   /api/v1/analyses/{job_id}/retry
GET    /api/v1/analyses/{job_id}/metrics
GET    /api/v1/analyses/{job_id}/findings
GET    /api/v1/analyses/{job_id}/events
```

## 12. Docker Compose with PostgreSQL

```powershell
docker compose up --build
```

Compose starts:

```text
db       PostgreSQL 16
migrate  one-time Alembic upgrade
api      FastAPI/Uvicorn on port 8000
worker   persistent analysis worker
```

Open:

```text
http://localhost:8000/docs
```

Stop services:

```powershell
docker compose down
```

Remove all database and upload data as well:

```powershell
docker compose down -v
```

## 13. Important M6 scope

M6 persists and serves the existing rule-based analysis pipeline. M5 model
artifacts remain available through the CLI, but loading ML predictions into the
web analysis job and generating SHAP/LIME explanations belong to M7.
Authentication and multi-tenant authorization are also not included in this
local/research M6 service; do not expose it directly to the public Internet
without adding an authenticated gateway and deployment controls.

## 14. Run tests

```powershell
python -m pytest
```

Coverage:

```powershell
python -m pytest --cov=src/codesmell --cov-report=term-missing --cov-report=html
```
