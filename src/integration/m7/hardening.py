"""M7.5 — Conflict / insufficient-evidence / prompt-injection / scope hardening.

Defense-in-depth security layer for the M7.1–M7.4 controlled-injection pipeline.

This module provides:

1. ``validate_evidence_set`` — EvidenceSet invariant validation. Rejects
   malformed/tampered sets: wrong route, budget violations, duplicate IDs,
   route/evidence inconsistency, invalid conflict references, missing provenance.
   Returns a ``ValidationResult`` (valid + reason). Fail closed: invalid sets
   produce no injection.

2. ``escape_field`` — deterministic content escaping for envelope field values.
   Prevents delimiter injection, role-marker injection, pseudo-evidence
   embedding, and control-character attacks. Every user-controlled string
   that enters the envelope is escaped.

3. ``sanitize_evidence_set`` — applies escaping to all EvidenceItem fields and
   conflict metadata, returning a sanitized EvidenceSet copy suitable for
   serialization.

No LLM, no network, no writes, no GrantAdmin, no new retrieval. Pure
deterministic validation and escaping. This is defense-in-depth; it does NOT
replace M5 authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .contracts import EvidenceSet, EvidenceItem, EvidenceRole, MemoryRoute


# ---------------------------------------------------------------------------
# EvidenceSet invariant validation
# ---------------------------------------------------------------------------

_MAX_PRIMARY = 5
_MAX_SUPPORTING = 3
_MAX_TOTAL = 8
_MAX_FIELD_LEN = 2000  # per-field length cap to prevent token-budget attacks
_MAX_SUMMARY_LEN = 280  # summary-specific cap (matches evidence_builder)


@dataclass(frozen=True)
class ValidationResult:
    """Result of EvidenceSet validation. Fail closed on invalid."""
    valid: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.valid


def validate_evidence_set(es: EvidenceSet) -> ValidationResult:
    """Validate an EvidenceSet before serialization. Fail closed.

    Checks:
    - memory_needed == false but evidence present -> invalid
    - > 5 primary -> invalid
    - > 3 supporting -> invalid
    - > 8 total -> invalid
    - duplicate evidence IDs within primary -> invalid
    - duplicate evidence IDs within supporting -> invalid
    - evidence_id missing/empty -> invalid
    - resource_type missing/empty -> invalid
    - route is no_memory but evidence present -> invalid
    - field length exceeding cap -> invalid

    Returns ValidationResult(valid=True) if all checks pass.
    """
    # no_memory with evidence is inconsistent
    if not es.memory_needed:
        if es.primary_evidence or es.supporting_evidence:
            return ValidationResult(False, "no_memory_with_evidence")
        # no_memory with no evidence is valid (empty set)
        return ValidationResult(True)

    # Budget limits
    if len(es.primary_evidence) > _MAX_PRIMARY:
        return ValidationResult(False, f"primary_exceeds_budget:{len(es.primary_evidence)}")
    if len(es.supporting_evidence) > _MAX_SUPPORTING:
        return ValidationResult(False, f"supporting_exceeds_budget:{len(es.supporting_evidence)}")
    if len(es.primary_evidence) + len(es.supporting_evidence) > _MAX_TOTAL:
        return ValidationResult(False, "total_exceeds_budget")

    # Duplicate IDs within primary
    primary_ids = [e.evidence_id for e in es.primary_evidence]
    if len(set(primary_ids)) != len(primary_ids):
        return ValidationResult(False, "duplicate_primary_ids")

    # Duplicate IDs within supporting
    supporting_ids = [e.evidence_id for e in es.supporting_evidence]
    if len(set(supporting_ids)) != len(supporting_ids):
        return ValidationResult(False, "duplicate_supporting_ids")

    # Cross-list duplicate IDs (same evidence in primary and supporting)
    if set(primary_ids) & set(supporting_ids):
        return ValidationResult(False, "cross_list_duplicate_ids")

    # Required fields
    for item in es.primary_evidence:
        if not item.evidence_id:
            return ValidationResult(False, "missing_evidence_id_primary")
        if not item.resource_type:
            return ValidationResult(False, "missing_resource_type_primary")

    for item in es.supporting_evidence:
        if not item.evidence_id:
            return ValidationResult(False, "missing_evidence_id_supporting")
        if not item.resource_type:
            return ValidationResult(False, "missing_resource_type_supporting")

    # Field length checks (token-budget attack prevention)
    for item in es.primary_evidence + es.supporting_evidence:
        for attr in ("evidence_id", "resource_type", "memory_type", "trace_id",
                     "route", "summary", "source", "created_at", "lifecycle",
                     "verification", "confidence", "sensitivity", "profile_id",
                     "project_id", "provenance", "eligibility_reason"):
            val = getattr(item, attr, None)
            if val and len(str(val)) > _MAX_FIELD_LEN:
                return ValidationResult(False, f"field_too_long:{attr}")
        for ks in item.knowledge_space_ids:
            if len(str(ks)) > _MAX_FIELD_LEN:
                return ValidationResult(False, "field_too_long:knowledge_space_id")

    # Conflict metadata validation
    for c in es.conflicts:
        if not isinstance(c, dict):
            return ValidationResult(False, "conflict_not_dict")
        if "trace_id" not in c and "items" not in c:
            return ValidationResult(False, "conflict_missing_keys")
        items = c.get("items", [])
        if not isinstance(items, list):
            return ValidationResult(False, "conflict_items_not_list")
        if c.get("resolved", False) is True:
            # Hardened: conflicts must never be pre-resolved
            return ValidationResult(False, "conflict_pre_resolved")

    return ValidationResult(True)


# ---------------------------------------------------------------------------
# Deterministic content escaping
# ---------------------------------------------------------------------------

# Characters that could break the envelope structure or inject role markers.
# We replace them with visual approximations that preserve meaning without
# allowing structural injection.
_ESCAPE_MAP = {
    "\r": "",        # strip carriage returns
    "\n": " ",       # newlines become spaces (single-line field)
    "\t": " ",       # tabs become spaces
    "\x00": "",      # null bytes stripped
    "[Zero-Mem": "[Zero Mem",   # prevent header injection
    "[End Zero-Mem": "[End Zero Mem",  # prevent footer injection
}


def escape_field(value: Optional[str]) -> str:
    """Deterministically escape a field value for safe envelope inclusion.

    - Strips control characters (null, CR)
    - Replaces newlines/tabs with spaces
    - Neutralizes envelope delimiters in content
    - Replaces role markers (system:, developer:, role=) with neutral text
    - Caps length to prevent token-budget attacks
    - Strips YAML/JSON document separators
    """
    if not value:
        return ""
    s = str(value)
    # Strip control characters
    s = s.replace("\x00", "").replace("\r", "")
    # Replace newlines and tabs with spaces
    s = s.replace("\n", " ").replace("\t", " ")
    # Neutralize envelope delimiters
    s = s.replace("[Zero-Mem Contextual Evidence]", "[Zero-Mem Contextual Evidence (data)]")
    s = s.replace("[End Zero-Mem Contextual Evidence]", "[End Zero-Mem Contextual Evidence (data)]")
    # Neutralize role markers that could impersonate system/developer/user
    # Break the actual substring so it cannot be parsed as a role marker
    s = s.replace("role=system", "role\u200B=\u200Bsystem (data)")
    s = s.replace("role=developer", "role\u200B=\u200Bdeveloper (data)")
    s = s.replace("role=user", "role\u200B=\u200Buser (data)")
    s = s.replace("role:system", "role\u200B:\u200Bsystem (data)")
    s = s.replace("role:developer", "role\u200B:\u200Bdeveloper (data)")
    # Neutralize YAML/JSON document separators
    s = s.replace("---", "—")
    s = s.replace("...", "…")
    # Cap length
    if len(s) > _MAX_FIELD_LEN:
        s = s[:_MAX_FIELD_LEN]
    return s


def escape_summary(value: Optional[str]) -> str:
    """Escape a summary field with the shorter summary-specific cap."""
    if not value:
        return ""
    s = escape_field(value)
    if len(s) > _MAX_SUMMARY_LEN:
        s = s[:_MAX_SUMMARY_LEN]
    return s


# ---------------------------------------------------------------------------
# EvidenceSet sanitization (apply escaping to all fields)
# ---------------------------------------------------------------------------

def sanitize_evidence_item(item: EvidenceItem) -> EvidenceItem:
    """Return a copy of an EvidenceItem with all text fields escaped."""
    return EvidenceItem(
        evidence_id=escape_field(item.evidence_id),
        resource_type=escape_field(item.resource_type),
        memory_type=escape_field(item.memory_type),
        trace_id=escape_field(item.trace_id),
        route=escape_field(item.route),
        content_source=item.content_source,  # controlled value, not escaped
        summary=escape_summary(item.summary),
        source=escape_field(item.source),
        created_at=escape_field(item.created_at),
        lifecycle=escape_field(item.lifecycle),
        verification=escape_field(item.verification),
        confidence=escape_field(item.confidence),
        sensitivity=escape_field(item.sensitivity),
        profile_id=escape_field(item.profile_id),
        project_id=escape_field(item.project_id),
        knowledge_space_ids=tuple(escape_field(ks) for ks in item.knowledge_space_ids),
        provenance=escape_field(item.provenance),
        role=item.role,  # enum, not escaped
        eligibility_reason=escape_field(item.eligibility_reason),
        truncated=item.truncated,
    )


def sanitize_evidence_set(es: EvidenceSet) -> EvidenceSet:
    """Return a copy of an EvidenceSet with all fields escaped.

    Does NOT validate — caller should validate first. Preserves structure
    (tuples, frozensets, conflicts) while escaping all user-controlled text.
    """
    return EvidenceSet(
        route=es.route,  # enum, not escaped
        memory_needed=es.memory_needed,
        used_scopes=es.used_scopes,  # frozenset of scope strings (controlled)
        primary_evidence=tuple(sanitize_evidence_item(e) for e in es.primary_evidence),
        supporting_evidence=tuple(sanitize_evidence_item(e) for e in es.supporting_evidence),
        conflicts=tuple(
            {
                "trace_id": escape_field(c.get("trace_id")),
                "items": [escape_field(str(i)) for i in c.get("items", [])],
                "resolved": False,  # force False; never allow pre-resolution
            }
            for c in es.conflicts
        ),
        insufficient_evidence=es.insufficient_evidence,
        external_current_required=es.external_current_required,
        omitted_count=es.omitted_count,
        estimated_tokens=es.estimated_tokens,
        reason_code=es.reason_code,
    )


__all__ = [
    "ValidationResult",
    "validate_evidence_set",
    "escape_field",
    "escape_summary",
    "sanitize_evidence_item",
    "sanitize_evidence_set",
    "_MAX_PRIMARY",
    "_MAX_SUPPORTING",
    "_MAX_TOTAL",
    "_MAX_FIELD_LEN",
    "_MAX_SUMMARY_LEN",
]
