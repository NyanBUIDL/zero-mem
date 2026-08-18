from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from zero_mem import CoreConfig, PublicClient

MATRIX = Path(__file__).resolve().parents[2] / "artifacts/control/COMPATIBILITY-MATRIX.yaml"


def test_matrix_freezes_policy_and_local_linux_row() -> None:
    text = MATRIX.read_text()
    assert 'python_range: ">=3.11,<3.14"' in text
    assert "support_classification: SUPPORTED" in text
    assert "support_classification: NOT_SUPPORTED" in text
    assert "qualification_status: QUALIFICATION_PENDING" in text
    assert "fts5_requirement: REQUIRED" in text


def test_current_python_is_inside_declared_range() -> None:
    assert (3, 11) <= sys.version_info[:2] < (3, 14)


def test_current_sqlite_has_required_fts5_capability() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        assert connection.execute("select sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0] == 1
    finally:
        connection.close()


def test_unavailable_public_capability_is_typed() -> None:
    client = PublicClient.open(CoreConfig(enabled=False))
    result = client.search({"query": "test"})
    assert result.status == "CAPABILITY_UNAVAILABLE"
    assert result.reason_code == "CAPABILITY_NOT_IMPLEMENTED"
    client.shutdown()
