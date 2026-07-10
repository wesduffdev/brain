"""Outcome-prediction ML: feature/label encoding, the model, and the trainer.

This package is the situated being's *first neural network* (BRIEF §11): a small
multi-label net that maps (object properties + action + context) to likely
outcomes. Encoding (`encode_features`) is pure and lives in the lean runtime so
inference can share it; the model and trainer (`outcome_model`,
`train_outcome_model`) pull in PyTorch, a training-only dependency imported
lazily so importing this package never requires torch.
"""
