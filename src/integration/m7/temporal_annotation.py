"""V130-04 — bounded temporal annotation of an EvidenceSet via M8.4.

Annotation-only integration: given a VALIDATED EvidenceSet, the M5
AuthorizedReadService, the derived-store connection and an explicit ``as_of``,
run the verified M8.4 ``read_temporal`` for each ALREADY-AUTHORIZED resource in
the set (authorization-first, per-resource seed) and attach a bounded DATA-ONLY
:class:`EvidenceTemporalInfo` to ``EvidenceSet.temporal``.

Invariants (docs/v1.3.0/plans/V130-04-SPEC.md):
- Never changes selection/order/budget/roles. Stale/superseded is SHOWN, not
  filtered.
- Authorization-first: an unauthorized resource contributes nothing (M8.4 returns
  an empty authorized=False result; it is skipped entirely, counted only).
- Fail-open exactly like M8.3 graph enrichment: any temporal-read failure keeps
  the upstream validated EvidenceSet untouched (temporal stays None).
- Bounded by M8.4's own MAX_HISTORY_VERSIONS (<=20) and the set's own item bound.
- Zero LLM, zero network, no writes.

The as_of value is validated HERE via the M8.1 temporal contract so every caller
path shares one fail-closed gate; malformed values raise TemporalError.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.m8.temporal_contract import normalize_timestamp
from src.m8.temporal_read import (
    MAX_HISTORY_VERSIONS,
    TemporalDimension,
    TemporalReadRequest,
    read_temporal,
)


@dataclass(frozen=True)
class ResourceTemporalInfo:
    """As-of view of ONE authorized resource. DATA only, no authority."""

    resource_id: str
    #: Whether the resource matches the as-of predicate on its own temporal row.
    valid_at_as_of: bool
    #: Bounded number of historical versions observed (<= MAX_HISTORY_VERSIONS).
    history_count: int
    #: Explicit supersession provenance carried verbatim (never an authority call).
    superseded_by: Optional[str] = None


@dataclass(frozen=True)
class EvidenceTemporalInfo:
    """Bounded temporal annotation attached to ``EvidenceSet.temporal``."""

    as_of: str
    dimension: str
    resources: List[ResourceTemporalInfo] = field(default_factory=list)
    #: Number of set resources skipped because M8.4 denied them (no leak of why).
    skipped_unauthorized: int = 0


def annotate_temporal(
    es: Any,
    service: Any,
    store_conn: sqlite3.Connection,
    requesting_profile_id: Optional[str],
    project_id: Optional[str],
    knowledge_space_id: Optional[str],
    as_of_raw: str,
) -> Any:
    """Return es with ``temporal`` populated; malformed as_of raises TemporalError.

    Any internal temporal-read failure degrades gracefully: the validated
    EvidenceSet is returned untouched with temporal=None (fail-open, same pattern
    as M8.3 graph enrichment).
    """
    # Fail-closed gate: malformed as_of raises before anything else runs.
    normalized = normalize_timestamp("as_of", as_of_raw)
    assert normalized is not None, "normalize_timestamp returned None for a present as_of"
    as_of = normalized.raw

    try:
        entries: List[ResourceTemporalInfo] = []
        skipped = 0
        seen: set = set()
        items = list(es.primary_evidence) + list(es.supporting_evidence)
        for e in items:
            rid = e.evidence_id
            if rid in seen:
                continue
            seen.add(rid)
            rtype = getattr(e, "resource_type", "") or ""
            if not rtype:
                # V130-04 Verifier F3: a missing resource_type is a mapping bug,
                # never a silent authorization skip.
                raise ValueError(f"evidence item missing resource_type: {rid}")
            req = TemporalReadRequest(
                requester=requesting_profile_id or "",
                resource_type=rtype,
                resource_id=rid,
                requesting_profile_id=requesting_profile_id,
                project_id=project_id,
                knowledge_space_id=knowledge_space_id,
                as_of=as_of,
            )
            res = read_temporal(store_conn, service, req)
            if not res.authorized:
                skipped += 1
                continue
            sup = None
            for p in (res.provenance or {}).values():
                val = p.get("superseded_by") if isinstance(p, dict) else None
                if val:
                    sup = str(val)
                    break
            entries.append(ResourceTemporalInfo(
                resource_id=rid,
                valid_at_as_of=bool(res.facts),
                history_count=len(res.facts),
                superseded_by=sup,
            ))
        info = EvidenceTemporalInfo(
            as_of=as_of or as_of_raw,
            dimension=TemporalDimension.TRANSACTION,
            resources=entries,
            skipped_unauthorized=skipped,
        )
        object.__setattr__(es, "temporal", info)
        return es
    except Exception:
        # Fail open: keep the validated EvidenceSet, temporal stays None.
        # (TemporalError from normalize_timestamp above is raised, not swallowed.)
        return es
