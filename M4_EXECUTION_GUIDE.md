# M4 Dataset Preparation and Human Labelling

This milestone creates research-ready human labels without treating the M3
rule detector as ground truth.

## 1. Install the updated project

Open PowerShell in the folder containing `pyproject.toml`:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install hatchling
python -m pip install -e ".[dev]"
```

Confirm the M4 version and commands:

```powershell
codesmell version
codesmell dataset --help
```

Expected version:

```text
codesmell 0.2.0
```

## 2. Create a review dataset

For one project:

```powershell
codesmell dataset create "D:\Projects\student-management" `
    --output "D:\Datasets\codesmell_m4"
```

For several projects in one dataset:

```powershell
codesmell dataset create `
    "D:\Projects\project-a" `
    "D:\Projects\project-b.zip" `
    "https://github.com/psf/requests" `
    --output "D:\Datasets\codesmell_m4"
```

Useful options:

```powershell
codesmell dataset create "D:\Projects\project-a" `
    --output "D:\Datasets\codesmell_m4" `
    --thresholds absolute `
    --negative-ratio 1.0 `
    --min-controls 3 `
    --seed 42 `
    --max-snippet-lines 200 `
    --overwrite
```

The output contains:

```text
codesmell_m4/
├── review_tasks.csv
├── candidate_evidence.csv
├── manifest.json
├── LABELING_GUIDE.md
└── snippets/
```

`review_tasks.csv` is deliberately blinded. It contains no metric features and
no M3 rule verdict. Do not give `candidate_evidence.csv` to reviewers until
the independent review is complete.

## 3. Label the tasks

Open `review_tasks.csv` in Excel. For every row, inspect the file listed under
`snippet_path` and complete these columns:

- `human_label`: `present`, `absent`, or `uncertain`
- `human_severity`: `low`, `medium`, `high`, or `critical` when present
- `reviewer_id`: reviewer name or anonymous code
- `review_notes`: optional justification
- `labelled_at`: optional RFC 3339 time, such as `2026-07-25T18:30:00+05:30`

For absent labels, leave `human_severity` blank or enter `none`.

## 4. Validate the review file

During labelling, blank rows are permitted:

```powershell
codesmell dataset validate `
    "D:\Datasets\codesmell_m4\review_tasks.csv"
```

Before finalisation, require every row to be reviewed:

```powershell
codesmell dataset validate `
    "D:\Datasets\codesmell_m4\review_tasks.csv" `
    --require-complete
```

The validator checks required columns, duplicate task IDs, allowed labels,
reviewer IDs, and severity consistency.

## 5. Compare two reviewers

Keep two copies of the same review sheet and have them labelled independently:

```powershell
codesmell dataset agreement `
    "D:\Datasets\reviewer_a.csv" `
    "D:\Datasets\reviewer_b.csv" `
    --conflicts "D:\Datasets\conflicts.csv"
```

The command reports exact agreement, Cohen's kappa, severity agreement, and
writes disagreements for adjudication.

## 6. Finalise canonical labels

After validation and adjudication:

```powershell
codesmell dataset finalize `
    "D:\Datasets\codesmell_m4\review_tasks.csv" `
    --output "D:\Datasets\labels.csv"
```

This creates:

```text
labels.csv
labels.csv.manifest.json
```

Uncertain rows are excluded from the binary training dataset. The final CSV
contains human labels and source provenance only. It does not contain the M3
rule verdict, rule conditions, or software metrics. M5 will recompute all
features from verified source code.

## 7. Run the test suite

```powershell
python -m pytest
```

The updated project contains 363 passing tests.
