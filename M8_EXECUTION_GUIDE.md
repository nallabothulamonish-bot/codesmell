# CodeSmell M8 — React Dashboard Execution Guide

M8 adds a responsive React and TypeScript dashboard to the M7 FastAPI, database, worker, ML prediction, explanation, and recommendation stack.

## What M8 provides

- Research dashboard with project, job, finding, and model summaries
- Safe `.zip` and `.py` project upload
- Public Git repository registration
- Rule, ML, and hybrid analysis configuration
- Persistent job progress, cancellation, retry, and event history
- Rule-finding filters and metric inspection
- ML probability, confidence, uncertainty, and threshold visualization
- Local feature-attribution charts
- Refactoring recommendations with validation checklists
- Trusted model registry enable/disable controls
- Dark/light appearance and responsive navigation
- Nginx production serving and API reverse proxy
- Docker Compose integration

## Prerequisites

- Python 3.11 or later
- Node.js 20 or later; Node.js 22 is recommended
- Git for public repository analysis
- Docker Desktop only for the container workflow

## Option A — Local development

### 1. Install and start the backend

From the project root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
codesmell db upgrade
codesmell api serve --host 127.0.0.1 --port 8000 --reload
```

The FastAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

### 2. Start the worker in a second terminal

```powershell
cd codesmell
.venv\Scripts\Activate.ps1
codesmell worker run
```

### 3. Install and start the frontend in a third terminal

```powershell
cd codesmell\frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`, so no frontend API URL needs to be configured for normal local development.

## Option B — Complete Docker deployment

From the project root:

```powershell
docker compose up --build
```

Open the complete application:

```text
http://localhost:8080
```

Backend API documentation remains available at:

```text
http://localhost:8000/docs
```

The Compose stack starts PostgreSQL, migration service, FastAPI, background worker, and the Nginx frontend.

## Register an M5 model

ML and hybrid analysis require at least one trusted, enabled model:

```powershell
codesmell model register `
    "D:\Datasets\m5\models\long_method\logistic" `
    --name "Long Method Logistic Regression"
```

Verify and list it:

```powershell
codesmell model verify MODEL_UUID
codesmell model list
```

The model then appears on the **Model Registry** page and in the project analysis configuration dialog.

## Dashboard workflow

1. Open **Projects**.
2. Upload a `.zip`/`.py` file or register a public HTTPS repository.
3. Select **Analyze**.
4. Choose rule, ML, or hybrid mode.
5. Select threshold mode and minimum severity.
6. For ML/hybrid mode, select one or more enabled models.
7. Start the job.
8. Keep the worker running while the analysis progresses.
9. Inspect Overview, Findings, Metrics, ML & XAI, Recommendations, and Events.

## Frontend tests and production build

```powershell
cd frontend
npm install
npm test
npm run build
```

The production bundle is generated in:

```text
frontend/dist/
```

Preview it locally:

```powershell
npm run preview
```

## Backend tests

From the project root:

```powershell
python -m pytest
```

## Optional remote API URL

The frontend uses same-origin `/api` calls by default. To connect a development build to another backend, create `frontend/.env.local`:

```text
VITE_API_ROOT=https://your-api.example.org
```

The backend must then permit the frontend origin:

```text
CODESMELL_API__CORS_ORIGINS=["https://your-dashboard.example.org"]
```

For the Docker deployment supplied with M8, Nginx reverse proxying is preferred and no cross-origin configuration is required.

## Security notes

- Uploaded source is parsed statically and is never executed.
- The browser does not accept model files. Model registration remains an administrator CLI operation.
- Nginx limits uploaded request bodies to 200 MB, matching the backend default.
- Model artifact integrity is verified in the M7 registry before deserialization.
- Production deployments should use HTTPS, non-default PostgreSQL credentials, backups, and restricted administrative access.

## Main frontend structure

```text
frontend/
├── src/
│   ├── api/
│   ├── components/
│   ├── features/analysis/
│   ├── layouts/
│   ├── pages/
│   ├── types/
│   └── utils/
├── Dockerfile
├── nginx.conf
├── package.json
└── vite.config.ts
```
