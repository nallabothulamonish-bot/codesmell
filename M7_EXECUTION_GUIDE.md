# CodeSmell M7 Execution Guide

M7 connects the M5 trained models to the M6 FastAPI worker. It adds a trusted
model registry, ML and hybrid analysis jobs, confidence and uncertainty,
SHAP/local feature attributions, and smell-specific refactoring guidance.

## 1. Install or upgrade the project

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
codesmell 0.5.0
```

M7 adds `numpy` and `shap`. Installation can take longer than M6 because SHAP
includes compiled numerical components.

## 2. Upgrade the database

```powershell
codesmell db upgrade
```

M7 adds:

```text
model_artifacts
ml_predictions
prediction_explanations
recommendations
```

It also adds `model_ids` and `explain_predictions` to `analysis_jobs`.

## 3. Register a trusted M5 model

An M5 model folder must contain:

```text
model.joblib
model_card.json
```

Example:

```powershell
codesmell model register `
    "D:\Datasets\m5\models\long_method\logistic" `
    --name "Long Method Logistic Regression"
```

Registration performs these checks before the model is accepted:

- `model.joblib` SHA-256 matches `model_card.json`.
- `smell_type` is a known CodeSmell smell.
- Model kind is `logistic` or `random_forest`.
- The threshold is between 0 and 1.
- Feature names are unique and begin with `feature__`.
- The exact feature order is preserved.

The verified files are copied to:

```text
<CODESMELL_API__STORAGE_ROOT>/models/<model-id>/
```

### Important security rule

Only register models that you trained or obtained from a trusted, verified
source. `joblib` uses pickle-based deserialization. A malicious model file can
execute code when loaded. M7 therefore does not provide a public model-upload
API.

## 4. List and verify models

```powershell
codesmell model list
```

Recheck a stored model:

```powershell
codesmell model verify MODEL_UUID
```

Disable a model for new analyses:

```powershell
codesmell model set-enabled MODEL_UUID --disabled
```

Enable it again:

```powershell
codesmell model set-enabled MODEL_UUID --enabled
```

## 5. Start the API and worker

### Terminal 1 — API

```powershell
.venv\Scripts\Activate.ps1
codesmell api serve --host 127.0.0.1 --port 8000 --reload
```

### Terminal 2 — worker

```powershell
.venv\Scripts\Activate.ps1
codesmell worker run
```

Open Swagger:

```text
http://127.0.0.1:8000/docs
```

## 6. Upload a project

PowerShell with curl:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/projects/upload" `
  -F "file=@D:\Projects\student-management.zip" `
  -F "name=Student Management"
```

Copy the returned project `id`.

## 7. Create an ML analysis

Use every enabled registered model:

```powershell
curl.exe -X POST `
  "http://127.0.0.1:8000/api/v1/projects/PROJECT_ID/analyses" `
  -H "Content-Type: application/json" `
  -d '{
    "analysis_kind": "ml",
    "explain_predictions": true
  }'
```

Use selected models only:

```powershell
curl.exe -X POST `
  "http://127.0.0.1:8000/api/v1/projects/PROJECT_ID/analyses" `
  -H "Content-Type: application/json" `
  -d '{
    "analysis_kind": "ml",
    "model_ids": ["MODEL_UUID_1", "MODEL_UUID_2"],
    "explain_predictions": true
  }'
```

## 8. Create a hybrid analysis

A hybrid job stores both M3 rule findings and M7 model predictions:

```powershell
curl.exe -X POST `
  "http://127.0.0.1:8000/api/v1/projects/PROJECT_ID/analyses" `
  -H "Content-Type: application/json" `
  -d '{
    "analysis_kind": "hybrid",
    "threshold_mode": "absolute",
    "min_severity": "low",
    "model_ids": ["MODEL_UUID"],
    "explain_predictions": true
  }'
```

Copy the returned analysis job `id`.

## 9. Check job status

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID"
```

A completed M7 summary contains:

```json
{
  "analysis_kind": "hybrid",
  "detection": {
    "stored_findings": 4
  },
  "machine_learning": {
    "models": 1,
    "predictions": 12,
    "positive_predictions": 3,
    "explanations": 12,
    "recommendations": 3
  }
}
```

## 10. Retrieve predictions

All predictions:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/predictions"
```

Only positive predictions:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/predictions?predicted=true"
```

Filter by smell:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/predictions?smell=long_method"
```

Each prediction includes:

- `probability`: estimated positive-class probability.
- `threshold`: model-card decision threshold.
- `prediction`: whether probability meets that threshold.
- `confidence`: probability of the selected class.
- `uncertainty`: `1 - confidence`; values near 0.5 are least certain.

## 11. Retrieve explanations

All explanations for a job:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/explanations"
```

One prediction explanation:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/predictions/PREDICTION_ID/explanation"
```

Explanation methods:

```text
shap_linear
shap_tree
linear_contribution
tree_importance_fallback
value_deviation_fallback
```

`shap_linear` is used for the scaled Logistic Regression pipeline.
`shap_tree` is used for Random Forest. The fallback methods keep the service
usable if SHAP cannot explain a future compatible estimator.

Each top feature records:

- Feature name
- Raw metric value
- Local contribution
- Whether it increases or decreases smell risk
- Absolute importance rank

## 12. Retrieve recommendations

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/recommendations"
```

Filter:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/analyses/JOB_ID/recommendations?smell=long_parameter_list&priority=high"
```

One prediction recommendation:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/predictions/PREDICTION_ID/recommendation"
```

Recommendations contain:

- Refactoring title and summary
- Priority based on model probability
- Smell-specific actions
- Highest-contributing metric evidence
- Behaviour-preserving validation steps

They are suggestions, not automatic transformations. Review them against the
actual domain design and tests.

## 13. Model API

List enabled models:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/models?enabled=true"
```

Disable a model through the API:

```powershell
curl.exe -X PATCH `
  "http://127.0.0.1:8000/api/v1/models/MODEL_UUID" `
  -H "Content-Type: application/json" `
  -d '{"enabled": false}'
```

Registration remains CLI-only for security.

## 14. Explainability settings

In `.env`:

```text
CODESMELL_EXPLAINABILITY__TOP_FEATURES=8
CODESMELL_EXPLAINABILITY__PREFER_SHAP=true
CODESMELL_EXPLAINABILITY__RECOMMENDATIONS_FOR_POSITIVE_ONLY=true
```

Set `PREFER_SHAP=false` to use deterministic model-native contributions.
Set `RECOMMENDATIONS_FOR_POSITIVE_ONLY=false` to create recommendations for
negative predictions as well, usually only for research inspection.

## 15. Docker

Build and start PostgreSQL, migrations, API and worker:

```powershell
docker compose up --build
```

Register models from the host CLI only when the CLI shares the same database
and storage volume. For a simple Docker workflow, copy the trusted model folder
into the running API container and execute:

```powershell
docker compose exec api codesmell model register `
  /tmp/model --name "Long Method Logistic Regression"
```

For production, mount a read-only trusted-model staging directory and copy from
that directory during registration. Never expose a public endpoint that accepts
`model.joblib` files.

## 16. Run tests

```powershell
python -m pytest
```

Coverage:

```powershell
python -m pytest --cov=src/codesmell --cov-report=term-missing
```

M7 verification includes registry integrity, tamper detection, Logistic and
Random Forest explanations, hybrid worker execution, database persistence and
API retrieval.

## 17. Common errors

### `no enabled ML models match this analysis request`

Register at least one model or enable the selected model UUID.

### `model SHA-256 does not match model card`

The model file changed after training, or the wrong card was paired with it.
Re-export the M5 artifact. Do not edit the hash manually.

### `model requires unavailable metrics`

The model-card feature schema does not match the current entity type or metrics
engine. Train again using `codesmell ml prepare` from the same CodeSmell code
line.

### `explanation not found`

The job was created with `explain_predictions=false`, or the prediction does not
belong to that job.

### scikit-learn version warning while loading

Model persistence across different scikit-learn versions is not guaranteed.
Use the same dependency environment used for M5 training, or retrain the model
with the current project version.
