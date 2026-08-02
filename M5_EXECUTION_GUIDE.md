# CodeSmell M5 Execution Guide

M5 adds leakage-safe machine-learning preparation, project-level holdout
training, grouped inner hyperparameter tuning, and leave-one-project-out
cross-project evaluation.

## 1. Install the updated project

Open PowerShell in the folder containing `pyproject.toml`:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

Verify:

```powershell
codesmell version
codesmell ml --help
```

Expected version:

```text
codesmell 0.3.0
```

## 2. M5 input requirements

M5 does not train from `review_tasks.csv` or `candidate_evidence.csv`.
First complete M4 and produce the canonical labels file:

```powershell
codesmell dataset validate "D:\Datasets\m4\review_tasks.csv" --require-complete
codesmell dataset finalize "D:\Datasets\m4\review_tasks.csv" `
    --output "D:\Datasets\m4\labels.csv"
```

Use human-reviewed labels only. Do not substitute M3 rule predictions as labels.
Doing so would create circular evaluation in which the model merely learns the
rules that generated its targets.

You must retain the exact source versions used during M4. M5 verifies:

- Project content fingerprint
- Source-file SHA-256
- Entity identifier
- Entity type
- Qualified name and relative path

A changed or missing source project is rejected rather than silently joined.

## 3. Recompute features from original source

Provide every original project represented in `labels.csv`:

```powershell
codesmell ml prepare "D:\Datasets\m4\labels.csv" `
    "D:\ResearchProjects\project-a" `
    "D:\ResearchProjects\project-b.zip" `
    "https://github.com/example/project-c" `
    --output "D:\Datasets\m5\training_features.csv"
```

Use `--overwrite` only when deliberately replacing an existing output.

Generated files:

```text
training_features.csv
training_features.csv.manifest.json
```

The CSV contains human labels plus software metrics freshly calculated by this
project. Class and method features remain separate. Features are written with
the `feature__` prefix.

## 4. Inspect the project-level split

```powershell
codesmell ml split "D:\Datasets\m5\training_features.csv" `
    --output "D:\Datasets\m5\project_split.csv" `
    --test-size 0.20 `
    --seed 42
```

Restrict the command to selected smells by repeating `--smell`:

```powershell
codesmell ml split "D:\Datasets\m5\training_features.csv" `
    --output "D:\Datasets\m5\method_split.csv" `
    --smell long_method `
    --smell complex_method
```

The same project fingerprint will never occur in both train and test for a
smell. The split report also states when a test partition contains only one
class. In that case ROC-AUC and PR-AUC are reported as unavailable rather than
invented.

## 5. Train project-holdout models

Train Logistic Regression and Random Forest models:

```powershell
codesmell ml train "D:\Datasets\m5\training_features.csv" `
    --output "D:\Datasets\m5\models" `
    --models logistic,random_forest `
    --test-size 0.20 `
    --seed 42 `
    --threshold 0.50 `
    --min-samples 10 `
    --min-projects 2
```

Train one smell only:

```powershell
codesmell ml train "D:\Datasets\m5\training_features.csv" `
    --output "D:\Datasets\m5\long_method_model" `
    --models logistic,random_forest `
    --smell long_method
```

M5 creates a separate binary model for each smell. It never combines class and
method entities into one feature matrix.

### Nested evaluation design

For every smell and model:

1. Entire projects are assigned to the outer train or test partition.
2. Hyperparameters are selected using grouped cross-validation only within the
   outer training projects.
3. The untouched outer test projects are evaluated once.
4. The fitted model, exact feature order, selected parameters, project lists,
   metrics, and SHA-256 are saved.

Model output structure:

```text
models/
├── holdout_report.json
├── predictions.csv
└── long_method/
    ├── logistic/
    │   ├── model.joblib
    │   └── model_card.json
    └── random_forest/
        ├── model.joblib
        └── model_card.json
```

## 6. Run leave-one-project-out evaluation

```powershell
codesmell ml logo "D:\Datasets\m5\training_features.csv" `
    --output "D:\Datasets\m5\logo" `
    --models logistic,random_forest `
    --seed 42 `
    --threshold 0.50 `
    --min-samples 10 `
    --min-projects 2
```

For each smell, every project is held out once. Hyperparameter selection is
repeated only on the remaining projects in that fold.

Generated files:

```text
logo/
├── logo_report.json
└── logo_predictions.csv
```

`logo_report.json` includes:

- Per-project fold metrics
- Skipped-fold reasons
- Inner grouped-tuning details
- Micro metrics over all out-of-project predictions
- Macro mean across project folds

## 7. Metrics reported

M5 calculates:

- Accuracy
- Balanced accuracy
- Precision
- Recall
- Specificity
- F1-score
- Matthews correlation coefficient
- ROC-AUC
- PR-AUC
- Brier score
- TN, FP, FN and TP
- Positive and predicted-positive rates

For imbalanced smell datasets, prioritize MCC, F1 and PR-AUC rather than raw
accuracy alone.

## 8. Verify a saved model

The optional prediction command checks the model hash and exact feature schema
before loading it:

```powershell
codesmell ml predict "D:\Datasets\m5\training_features.csv" `
    "D:\Datasets\m5\models\long_method\logistic" `
    --output "D:\Datasets\m5\verified_predictions.csv"
```

This command is mainly for artifact verification and controlled evaluation.
M6 will connect saved models directly to newly analyzed projects through the
backend service.

## 9. Run tests

```powershell
python -m pytest
```

Coverage report:

```powershell
python -m pytest --cov=src/codesmell --cov-report=term-missing
```

The delivered M5 project contains 375 passing tests. Overall measured coverage
is 88 percent in the supplied environment.

## 10. Minimum research-data guidance

A command may technically run with two projects and ten rows, but that is only
a software acceptance threshold. For credible cross-project claims, collect
several independently developed projects and enough positive and negative
human labels for every reported smell.

Recommended reporting practice:

- Report project names, versions and fingerprints.
- Report positive/negative counts per smell and project.
- Publish all skipped folds and the reasons.
- Compare Logistic Regression, Random Forest and the M3 rule baseline.
- Report both micro and macro LOGO results.
- Keep uncertain human labels excluded from binary training.
- Do not tune on the held-out project or select the final model from its score.
