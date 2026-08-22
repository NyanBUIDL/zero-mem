import sys
from pathlib import Path

# Ensure the repository root is importable so tests can use package-style imports
# (e.g. `from tests.unit.test_m3_query import ...`) regardless of pytest's rootdir.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(autouse=True)
def _isolate_process_global_runtime_gate():
    """Restore process-global Zero-Mem runtime-gate state after every test.

    R124-10 regression: ``HermesBoundary.register()`` in OFF/invalid mode calls
    ``src.integration.zero_mem_runtime.configure(enabled=False, source="boundary")``,
    which mutates the module-level ``_default_runtime`` gate. A later test that
    composes a ``RegistrationAdapter``/``HermesReadAdapter`` from an explicit
    ``BridgeConfig(enabled=True, ...)`` then observes a disabled global gate and
    silently opens NO writer/read surface (e.g. ``test_wp25_runtime_ownership``
    canonical JSONL never created, ``test_wp31`` sidecar never started).

    That product fail-closed behavior is intentional and asserted
    (``test_wp31_boundary_cannot_reenable_disabled_global_runtime``); the defect
    was TEST isolation — one test's process-global mutation leaked into the next.
    This fixture snapshots both module-level gate cells before each test and
    restores them afterwards, making test order irrelevant. It changes no product
    behavior and weakens no assertion.

    A passing focused suite in either directory order is the regression evidence.
    """
    from src.integration import zero_mem_runtime
    from zero_mem import hermes_integration

    gate_snapshot = zero_mem_runtime._default_runtime
    disabled_snapshot = hermes_integration._BOUNDARY_DISABLED_RUNTIME
    try:
        yield
    finally:
        zero_mem_runtime._default_runtime = gate_snapshot
        hermes_integration._BOUNDARY_DISABLED_RUNTIME = disabled_snapshot
