"""M5: leakage-safe machine-learning training and cross-project evaluation."""

from .features import prepare_feature_dataset
from .inference import predict_with_model
from .io import MLError, TrainingDataset, load_training_dataset
from .logo import leave_one_project_out
from .models import (
    FEATURE_PREFIX,
    ML_DATASET_SCHEMA_VERSION,
    ModelKind,
    SplitConfig,
    TrainingConfig,
)
from .splitting import ProjectSplit, project_holdout_split
from .training import train_holdout, write_split_assignments

__all__ = [
    "FEATURE_PREFIX",
    "ML_DATASET_SCHEMA_VERSION",
    "MLError",
    "ModelKind",
    "ProjectSplit",
    "SplitConfig",
    "TrainingConfig",
    "TrainingDataset",
    "leave_one_project_out",
    "load_training_dataset",
    "predict_with_model",
    "prepare_feature_dataset",
    "project_holdout_split",
    "train_holdout",
    "write_split_assignments",
]
