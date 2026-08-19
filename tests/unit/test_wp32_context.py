from __future__ import annotations

from src.integration.m7.context import ContextConfig, assemble_context
from src.integration.m7.contracts import EvidenceItem, EvidenceRole, EvidenceSet, MemoryRoute


def _item(evidence_id: str, role: EvidenceRole = EvidenceRole.SUPPORTING) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        resource_type="decision",
        memory_type="decision",
        summary=f"Decision summary {evidence_id}",
        source="trace-source",
        trace_id=f"trace-{evidence_id}",
        created_at="2026-08-19T00:00:00+00:00",
        lifecycle="active",
        verification="verified",
        provenance=f"trace:{evidence_id}",
        role=role,
    )


def test_context_is_deterministic_and_preserves_provenance() -> None:
    evidence = EvidenceSet(
        route=MemoryRoute.PROJECT,
        memory_needed=True,
        primary_evidence=(_item("E1", EvidenceRole.PRIMARY),),
        supporting_evidence=(_item("E2"),),
        estimated_tokens=20,
    )
    config = ContextConfig(max_bytes=4096, max_tokens=1000)

    first = assemble_context(evidence, config=config)
    second = assemble_context(evidence, config=config)

    assert first.status == "READY"
    assert first.context == second.context
    assert "trace:E1" in first.context
    assert "provenance" in first.context
    assert first.omitted_count == 0


def test_external_current_never_substitutes_historical_evidence() -> None:
    evidence = EvidenceSet(
        route=MemoryRoute.EXTERNAL_CURRENT,
        memory_needed=True,
        external_current_required=True,
        insufficient_evidence=True,
    )

    result = assemble_context(evidence, config=ContextConfig(max_bytes=4096, max_tokens=100))

    assert result.status == "READY"
    assert "external current data required" in result.context
    assert "Decision summary" not in result.context


def test_context_packer_omits_supporting_items_to_fit_byte_budget() -> None:
    evidence = EvidenceSet(
        route=MemoryRoute.PROJECT,
        memory_needed=True,
        primary_evidence=(_item("E1", EvidenceRole.PRIMARY),),
        supporting_evidence=(_item("E2"), _item("E3")),
    )
    unconstrained = assemble_context(evidence, config=ContextConfig(max_bytes=4096, max_tokens=1000))
    constrained = assemble_context(
        evidence,
        config=ContextConfig(max_bytes=len(unconstrained.context.encode("utf-8")) - 1, max_tokens=1000),
    )

    assert constrained.status == "READY"
    assert len(constrained.context.encode("utf-8")) <= len(unconstrained.context.encode("utf-8")) - 1
    assert constrained.omitted_count >= 1
    assert "trace:E1" in constrained.context


def test_context_rejects_non_positive_governed_limits() -> None:
    try:
        ContextConfig(max_bytes=0, max_tokens=100)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive byte budget must fail closed")

    try:
        ContextConfig(max_bytes=100, max_tokens=6001)
    except ValueError:
        pass
    else:
        raise AssertionError("token budget must not exceed governed ceiling")

    try:
        ContextConfig(max_bytes=100, max_tokens=0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive token budget must fail closed")


def test_external_current_discards_any_historical_items_fail_closed() -> None:
    evidence = EvidenceSet(
        route=MemoryRoute.EXTERNAL_CURRENT,
        memory_needed=True,
        external_current_required=True,
        insufficient_evidence=True,
        primary_evidence=(_item("STALE", EvidenceRole.PRIMARY),),
    )

    result = assemble_context(evidence)

    assert result.status == "READY"
    assert "external current data required" in result.context
    assert "STALE" not in result.context
    assert "Decision summary" not in result.context


def test_malformed_config_fails_closed_without_bypassing_ceilings() -> None:
    class OversizedConfig:
        max_bytes = 1024 * 1024
        max_tokens = 100_000

    result = assemble_context(EvidenceSet(route=MemoryRoute.NO_MEMORY, memory_needed=False), config=OversizedConfig())  # type: ignore[arg-type]

    assert result.status == "INVALID_INPUT"
    assert result.context == ""


def test_malformed_evidence_fails_closed_without_raising() -> None:
    evidence = EvidenceSet(
        route=MemoryRoute.PROJECT,
        memory_needed=True,
        primary_evidence=(None,),  # type: ignore[arg-type]
    )

    result = assemble_context(evidence)

    assert result.status == "INVALID_INPUT"
    assert result.context == ""
