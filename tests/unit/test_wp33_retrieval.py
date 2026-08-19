from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from benchmarks.wp33_lexical_benchmark import run_lexical_benchmark


def test_lexical_benchmark_is_reproducible_and_labeled(tmp_path: Path) -> None:
    first = run_lexical_benchmark(tmp_path / "first", corpus_size=25, repeats=3)
    second = run_lexical_benchmark(tmp_path / "second", corpus_size=25, repeats=3)

    assert first["benchmark_version"] == "wp33-lexical-v1"
    assert first["corpus_size"] == 25
    assert first["queries"] == 4
    assert first["authorization_before_candidate_discovery"] is True
    metrics = cast(list[dict[str, Any]], first["metrics"])
    assert all(row["precision_at_k"] == 0.1 for row in metrics)
    assert [
        {k: v for k, v in row.items() if k != "latency_ms"}
        for row in first["metrics"]
    ] == [
        {k: v for k, v in row.items() if k != "latency_ms"}
        for row in second["metrics"]
    ]
    assert first["retrieval_order_digest"] == second["retrieval_order_digest"]
    assert all(0.0 <= row["precision_at_k"] <= 1.0 for row in first["metrics"])
    assert all(0.0 <= row["recall_at_k"] <= 1.0 for row in first["metrics"])
    assert all(row["latency_ms"]["p50"] >= 0.0 for row in first["metrics"])
    assert all(row["latency_ms"]["p95"] >= 0.0 for row in first["metrics"])


def test_lexical_benchmark_writes_no_secret_or_absolute_fixture_path(tmp_path: Path) -> None:
    result = run_lexical_benchmark(tmp_path / "run", corpus_size=10, repeats=1)
    payload = json.dumps(result, sort_keys=True)

    assert str(tmp_path) not in payload
    assert "password" not in payload.lower()
    assert "api_key" not in payload.lower()


def test_benchmark_rejects_reused_or_symlinked_run_root(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    try:
        run_lexical_benchmark(existing, corpus_size=10, repeats=1)
    except ValueError as exc:
        assert str(exc) == "run_root_must_be_new"
    else:
        raise AssertionError("existing run root must fail closed")

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    try:
        run_lexical_benchmark(link, corpus_size=10, repeats=1)
    except ValueError as exc:
        assert str(exc) == "run_root_must_be_new"
    else:
        raise AssertionError("symlinked run root must fail closed")

    parent_target = tmp_path / "parent-target"
    parent_target.mkdir()
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(parent_target, target_is_directory=True)
    try:
        run_lexical_benchmark(parent_link / "child", corpus_size=10, repeats=1)
    except ValueError as exc:
        assert str(exc) == "run_root_symlink_component"
    else:
        raise AssertionError("symlinked parent must fail closed")
