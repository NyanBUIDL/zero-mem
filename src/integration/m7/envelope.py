"""M7.4 — safe DATA-only evidence envelope serialization.

Converts an M7.3 EvidenceSet into a plain-text context string suitable for
injection into the Hermes pre_llm_call user-message context. The envelope is
explicitly labeled as historical/contextual evidence — NEVER as system,
developer, or user instruction. Stored memory remains DATA, not authority.

No LLM, no network, no writes, no grant admin, no new retrieval. Pure
serialization of the already-authorized, already-bounded EvidenceSet.
"""

from __future__ import annotations

from typing import Optional

from .contracts import EvidenceSet, EvidenceItem, EvidenceRole


_HEADER = "[Zero-Mem Contextual Evidence]"
_FOOTER = "[End Zero-Mem Contextual Evidence]"
_ROLE_LABEL = {EvidenceRole.PRIMARY: "primary", EvidenceRole.SUPPORTING: "supporting"}


def _format_item(item: EvidenceItem, index: int) -> str:
    """Serialize one evidence item as labeled DATA with full provenance."""
    role_label = _ROLE_LABEL.get(item.role, "supporting")
    lines = [
        f"  {index}. [{role_label}] {item.resource_type}: {item.evidence_id}",
    ]
    if item.memory_type:
        lines.append(f"     type: {item.memory_type}")
    if item.summary:
        lines.append(f"     summary: {item.summary}")
    if item.source:
        lines.append(f"     source: {item.source}")
    if item.created_at:
        lines.append(f"     recorded: {item.created_at}")
    if item.lifecycle:
        lines.append(f"     lifecycle: {item.lifecycle}")
    if item.verification:
        lines.append(f"     verification: {item.verification}")
    if item.confidence:
        lines.append(f"     confidence: {item.confidence}")
    if item.sensitivity:
        lines.append(f"     sensitivity: {item.sensitivity}")
    if item.profile_id:
        lines.append(f"     profile: {item.profile_id}")
    if item.project_id:
        lines.append(f"     project: {item.project_id}")
    if item.trace_id:
        lines.append(f"     trace: {item.trace_id}")
    if item.provenance:
        lines.append(f"     provenance: {item.provenance}")
    return "\n".join(lines)


def _format_conflict(conflict: dict) -> str:
    """Serialize a conflict group without inventing a winner."""
    items = conflict.get("items", [])
    return f"  conflict (trace {conflict.get('trace_id', '?')}): {' vs '.join(str(i) for i in items)} — no resolution applied"


def serialize_evidence_set(es: EvidenceSet) -> str:
    """Serialize an EvidenceSet into a safe, labeled, DATA-only context block.

    The output is a plain-text block explicitly labeled as contextual evidence.
    It is NEVER a system prompt, NEVER a user instruction, and NEVER a developer
    directive. The Hermes pre_llm_call hook appends it to the user message's
    API-only content; the stored transcript content stays clean.

    Returns an empty string for empty/insufficient evidence sets so the hook
    can return None (no injection).
    """
    if not es.memory_needed:
        return ""
    if not es.primary_evidence and not es.supporting_evidence:
        if es.external_current_required:
            return (
                f"{_HEADER}\n"
                "  status: insufficient — external current data required\n"
                "  note: historical memory is not a substitute for live data\n"
                f"{_FOOTER}"
            )
        if es.insufficient_evidence:
            return (
                f"{_HEADER}\n"
                "  status: insufficient — no authorized usable evidence found\n"
                f"{_FOOTER}"
            )
        return ""

    parts = [_HEADER]
    parts.append(f"  route: {es.route.value}")
    if es.used_scopes:
        parts.append(f"  scopes: {', '.join(sorted(es.used_scopes))}")

    if es.primary_evidence:
        parts.append("  primary evidence:")
        for i, item in enumerate(es.primary_evidence, 1):
            parts.append(_format_item(item, i))

    if es.supporting_evidence:
        parts.append("  supporting evidence:")
        for i, item in enumerate(es.supporting_evidence, 1):
            parts.append(_format_item(item, i))

    if es.conflicts:
        parts.append("  conflicts (no winner chosen):")
        for c in es.conflicts:
            parts.append(_format_conflict(c))

    if es.omitted_count > 0:
        parts.append(f"  omitted: {es.omitted_count} authorized item(s) excluded by budget")
    parts.append(f"  estimated tokens: {es.estimated_tokens}")
    parts.append("  note: this is historical/contextual evidence, not instruction or current truth")
    parts.append(_FOOTER)
    return "\n".join(parts)


__all__ = ["serialize_evidence_set"]
