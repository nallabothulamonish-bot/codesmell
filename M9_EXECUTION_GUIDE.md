# CodeSmell M9 Execution Guide

M9 is the final platform milestone. It adds authentication and roles, stored
JSON/CSV/HTML/PDF reports, audit events, publication-oriented research exports,
frontend login and administration, and hardened production deployment.

## 1. Requirements

- Python 3.11 or 3.12
- Git
- Node.js 20 or later for the React frontend
- Docker Desktop when using the container stack

## 2. Install or upgrade

```powershell
cd codesmell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
codesmell db upgrade
codesmell version
```

Expected version:

```text
codesmell 0.7.0
```

The new Alembic revision creates:

```text
users
generated_reports
audit_events
```

## 3. Configure authentication

Copy `.env.example` to `.env`, then change the secret and initial administrator
credentials.

```text
CODESMELL_SECURITY__AUTH_ENABLED=true
CODESMELL_SECURITY__JWT_SECRET=replace-with-at-least-32-random-characters
CODESMELL_SECURITY__BOOTSTRAP_ADMIN_EMAIL=admin@example.org
CODESMELL_SECURITY__BOOTSTRAP_ADMIN_PASSWORD=ReplaceAdmin123
CODESMELL_SECURITY__BOOTSTRAP_ADMIN_NAME=CodeSmell Administrator
```

The bootstrap account is created only when the email does not already exist.
Remove the bootstrap password from the environment after initial deployment.

Authentication can remain disabled for isolated local tests:

```text
CODESMELL_SECURITY__AUTH_ENABLED=false
```

In production, M9 refuses to start unless authentication is enabled and the JWT
secret is non-default and at least 32 characters long.

## 4. User administration

Create accounts through the administrator CLI:

```powershell
codesmell user create admin@example.org `
    --name "Research Administrator" `
    --role admin

codesmell user create analyst@example.org `
    --name "Project Analyst" `
    --role analyst

codesmell user create viewer@example.org `
    --name "Read Only Reviewer" `
    --role viewer
```

Passwords are entered without echo when `--password` is omitted.

```powershell
codesmell user list
codesmell user set-password analyst@example.org
codesmell user set-enabled viewer@example.org --disabled
codesmell user set-enabled viewer@example.org --enabled
```

Roles:

| Role | Permissions |
|---|---|
| Administrator | Manage users and models; create/delete projects; run analyses; create/delete reports; view all results |
| Analyst | Create/delete projects; run/cancel/retry analyses; generate reports; view results |
| Viewer | Read-only access to projects, analyses, models and reports |

The final enabled administrator cannot be disabled or demoted through the API.

## 5. Run locally

### Terminal 1 - API

```powershell
.venv\Scripts\Activate.ps1
codesmell db upgrade
codesmell api serve --host 127.0.0.1 --port 8000 --reload
```

### Terminal 2 - worker

```powershell
.venv\Scripts\Activate.ps1
codesmell worker run
```

### Terminal 3 - frontend

```powershell
cd frontend
npm install
npm test
npm run dev
```

Open:

```text
Frontend: http://127.0.0.1:5173
API documentation: http://127.0.0.1:8000/docs
```

## 6. Obtain an API token

```powershell
$body = @{
    email = "admin@example.org"
    password = "ReplaceAdmin123"
} | ConvertTo-Json

$login = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/auth/token" `
    -ContentType "application/json" `
    -Body $body

$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/auth/me" -Headers $headers
```

## 7. Generate reports

Reports can be generated after an analysis has status `succeeded`.

### Browser

Open the analysis, choose **Reports**, and generate PDF, HTML, JSON, or CSV.

### API

```powershell
$reportBody = @{ format = "pdf"; title = "Final Code Quality Report" } | ConvertTo-Json
$report = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/reports" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $reportBody

Invoke-WebRequest `
    -Uri "http://127.0.0.1:8000/api/v1/reports/$($report.id)/download" `
    -Headers $headers `
    -OutFile $report.filename
```

### CLI

```powershell
codesmell report generate JOB_ID --format pdf
codesmell report generate JOB_ID --format html
codesmell report generate JOB_ID --format json
codesmell report generate JOB_ID --format csv
```

Format details:

- `json`: complete versioned evidence document.
- `csv`: ZIP containing project, analysis, models, findings, metrics,
  predictions, explanations and recommendations tables.
- `html`: standalone escaped report suitable for browser printing.
- `pdf`: paginated summary, findings, ML predictions and recommendations.

Every report stores a SHA-256 digest. The download endpoint recomputes and
checks the digest before returning the file.

## 8. Research evaluation export

Use real M5 outputs:

```powershell
codesmell research summarize `
    "D:\Research\models_m5\holdout_report.json" `
    "D:\Research\logo_m5\logo_report.json" `
    --output "D:\Research\paper_results"
```

Generated output:

```text
paper_results/
├── holdout_metrics.csv
├── logo_fold_metrics.csv
├── logo_metrics.csv
├── research_summary.json
├── RESEARCH_SUMMARY.md
└── figures/
    ├── logo_macro_f1.png
    ├── logo_macro_mcc.png
    ├── logo_macro_roc_auc.png
    └── logo_macro_pr_auc.png
```

`logo_metrics.csv` includes fold mean, standard deviation and approximate 95%
confidence-interval half-width for each metric. Report the per-project folds as
well as the aggregate; do not hide one-class held-out projects.

## 9. Docker development stack

```powershell
Copy-Item .env.example .env
# Edit local administrator credentials and secrets.
docker compose up --build
```

Open:

```text
http://localhost:8080
```

The stack starts PostgreSQL, migration, API, worker and frontend services.

## 10. Production deployment

Set required secrets:

```bash
export CODESMELL_DOMAIN=codesmell.example.org
export POSTGRES_PASSWORD='strong-random-database-password'
export CODESMELL_JWT_SECRET='at-least-32-random-characters-from-a-secret-manager'
export CODESMELL_ADMIN_EMAIL='admin@example.org'
export CODESMELL_ADMIN_PASSWORD='StrongInitial123'
```

Start:

```bash
docker compose -f docker-compose.production.yml up -d --build
```

Caddy terminates HTTPS and forwards to the Nginx frontend. The backend runs as a
non-root user with a read-only container filesystem, explicit persistent
volumes, dropped Linux capabilities and automatic migrations disabled.

After initial login:

1. Create a second administrator.
2. Verify that account.
3. Remove the bootstrap password from the environment.
4. Restart the API and worker.
5. Configure regular PostgreSQL and data-volume backups.

See `docs/DEPLOYMENT.md` and `docs/SECURITY.md`.

## 11. Backup PostgreSQL

```bash
docker compose -f docker-compose.production.yml --profile backup run --rm backup
```

Restore using `pg_restore` into a clean database after testing the dump in a
separate environment.

## 12. Verification commands

```powershell
python -m compileall -q src
python -m pytest
python -m pytest --cov=src/codesmell --cov-report=term-missing
python -m build --wheel

cd frontend
npm install
npm test
npm run build
```

## 13. Final milestone map

```text
M0-M3  Static ingestion, metrics and rule baseline
M4     Blinded human-labelling workflow
M5     Leakage-safe training and LOGO evaluation
M6     FastAPI, database and persistent workers
M7     Trusted models, XAI and recommendations
M8     React dashboard and Docker frontend
M9     Authentication, reports, audit, research exports and production release
```
