"""Public release-layer package for Zero-Mem."""

from .api import API_VERSION, AsyncClient, AsyncQueueFullError, AsyncTimeoutError, CapabilityResult, ClientClosedError, Health, InvalidRequestError, PublicClient, PublicReadService, ZeroMemAPIError
from .core import AppendReceipt, CaptureResult, CoreConfig, EventWriter, ZeroMemClient
from .recovery import FailureClass, RecoveryDiagnosis, diagnose
from .status import STATUS_SCHEMA_VERSION, StatusSnapshot, collect_status
from .sidecar import CAPABILITIES, CONTRACT_VERSION, LocalSidecar, SidecarConfig, SidecarError
from .version import __version__
from .local import open_local_client

__all__ = [
    "API_VERSION",
    "AsyncClient",
    "AsyncQueueFullError",
    "AsyncTimeoutError",
    "CapabilityResult",
    "ClientClosedError",
    "Health",
    "InvalidRequestError",
    "PublicClient",
    "PublicReadService",
    "open_local_client",
    "RecoveryDiagnosis",
    "STATUS_SCHEMA_VERSION",
    "StatusSnapshot",
    "LocalSidecar",
    "SidecarConfig",
    "SidecarError",
    "ZeroMemAPIError",
    "diagnose",
    "collect_status",
    "CaptureResult",
    "AppendReceipt",
    "CAPABILITIES",
    "CONTRACT_VERSION",
    "CoreConfig",
    "EventWriter",
    "FailureClass",
    "ZeroMemClient",
    "__version__",
]
