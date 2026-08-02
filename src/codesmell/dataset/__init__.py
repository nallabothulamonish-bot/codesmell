"""M4: reproducible, blinded human-labelling datasets."""

from .builder import LabelDatasetBuilder, SamplingConfig
from .io import (
    EVIDENCE_COLUMNS,
    LABEL_COLUMNS,
    REVIEW_COLUMNS,
    DatasetError,
    DatasetWriter,
    read_csv,
    write_final_labels,
)
from .models import (
    DATASET_SCHEMA_VERSION,
    CandidateEvidence,
    CandidateSource,
    DatasetBuildReport,
    HumanLabel,
    ProjectLabelBundle,
    ReviewTask,
    ReviewValidationReport,
    ValidationIssue,
)
from .validation import reviewer_agreement, validate_review_file

__all__ = [
    "DATASET_SCHEMA_VERSION",
    "EVIDENCE_COLUMNS",
    "LABEL_COLUMNS",
    "REVIEW_COLUMNS",
    "CandidateEvidence",
    "CandidateSource",
    "DatasetBuildReport",
    "DatasetError",
    "DatasetWriter",
    "HumanLabel",
    "LabelDatasetBuilder",
    "ProjectLabelBundle",
    "ReviewTask",
    "ReviewValidationReport",
    "SamplingConfig",
    "ValidationIssue",
    "read_csv",
    "reviewer_agreement",
    "validate_review_file",
    "write_final_labels",
]
