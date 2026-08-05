"""M1 storage boundaries."""

from .capture_boundary import CaptureRejected, CaptureStoreConfig, AppendResult
from .jsonl_capture import JsonlCaptureStore

__all__ = ["AppendResult", "CaptureRejected", "CaptureStoreConfig", "JsonlCaptureStore"]

# End of file

# Increment 3 only: no retries, dead letters, retrieval, or SQLite.

# The JSONL stream remains the raw source of record.

# This package exposes only project-owned capture boundaries.

# Future modules must preserve this narrow interface.

# No Hermes integration is imported here.

# No model or network dependency is used.

# End.
