"""V1.6.0 C1 RED-first — capture contract: canonical knowledge_space_ids.

Forward-only capture contract (ADR-V160-01 §3, plan C1):
- normalize_event accepts knowledge_space_ids (dedup preserving order).
- validation.py declares knowledge_space_ids in OPTIONAL_FIELDS and rejects
  non-list / non-string / empty / duplicate / over-length / over-count.
- production capture_adapter._envelope carries knowledge_space_ids (or legacy
  knowledge_space_id -> list) into the top-level envelope.
- canonical append (JsonlCaptureStore) preserves the field verbatim.

RED on current tree (no production V1.6.0 code yet); GREEN after C1.
"""
from __future__ import annotations

import json

import pytest

from src.capture.adapter import normalize_event
from src.capture.event_types import (
    MAX_KNOWLEDGE_SPACE_ID_LENGTH,
    MAX_KNOWLEDGE_SPACE_IDS,
)
from src.capture.validation import validate_envelope
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore

_AUDIT = [{"rule": "c1", "fields": []}]


def _env(ks=None, **over):
    return normalize_event(
        {"text": "hi", "redaction_audit": _AUDIT, **over},
        profile_id="p1", project_id="P", sequence=0,
        event_type="user_statement", source="hermes_chat",
        knowledge_space_ids=ks,
    )


class TestC1AdapterContract:
    def test_normalize_event_carries_knowledge_space_ids(self):
        env = _env(ks=["quant-theory", "engineering"])
        assert env["knowledge_space_ids"] == ["quant-theory", "engineering"]

    def test_dedup_preserves_order(self):
        env = _env(ks=["B", "A", "B", "C", "A"])
        assert env["knowledge_space_ids"] == ["B", "A", "C"]

    def test_payload_ks_also_honored(self):
        env = _env(ks=["A"])
        assert env["knowledge_space_ids"] == ["A"]

    def test_empty_list_explicitly_preserved(self):
        env = _env(ks=[])
        assert "knowledge_space_ids" in env
        assert env["knowledge_space_ids"] == []

    def test_none_omits_field(self):
        env = _env(ks=None)
        assert "knowledge_space_ids" not in env


class TestC1ValidationContract:
    def test_rejects_non_list(self):
        with pytest.raises(ValueError):
            validate_envelope(_env(ks="A"))

    def test_rejects_string_item(self):
        with pytest.raises(ValueError):
            validate_envelope(_env(ks=[1]))

    def test_rejects_empty_string_item(self):
        with pytest.raises(ValueError):
            validate_envelope(_env(ks=["A", "  "]))

    def test_rejects_duplicates(self):
        # Adapter dedups leniently; validation is the STRICT gate for
        # hand-crafted envelopes — inject the duplicate directly.
        env = _env(ks=["A"])
        env["knowledge_space_ids"] = ["A", "A"]
        with pytest.raises(ValueError):
            validate_envelope(env)

    def test_rejects_over_length(self):
        with pytest.raises(ValueError):
            validate_envelope(_env(ks=["x" * (MAX_KNOWLEDGE_SPACE_ID_LENGTH + 1)]))

    def test_rejects_over_count(self):
        with pytest.raises(ValueError):
            validate_envelope(_env(ks=[f"ks-{i}" for i in range(MAX_KNOWLEDGE_SPACE_IDS + 1)]))


class TestC1ProductionAdapter:
    def test_production_envelope_carries_ks(self):
        from types import SimpleNamespace
        from src.integration import capture_adapter
        mapped = SimpleNamespace(source="hermes", event_type="user_statement",
                                 hook="pre_tool_call")
        sanitized = {"text": "hi", "profile_id": "p1",
                     "knowledge_space_ids": ["quant-theory", "engineering"]}
        envelope = capture_adapter._envelope(mapped, sanitized)
        assert envelope["knowledge_space_ids"] == ["quant-theory", "engineering"]

    def test_production_envelope_legacy_singular(self):
        from types import SimpleNamespace
        from src.integration import capture_adapter
        mapped = SimpleNamespace(source="hermes", event_type="user_statement",
                                 hook="pre_tool_call")
        sanitized = {"text": "hi", "profile_id": "p1",
                     "knowledge_space_id": "legacy-ks"}
        envelope = capture_adapter._envelope(mapped, sanitized)
        assert envelope["knowledge_space_ids"] == ["legacy-ks"]


class TestC1CanonicalPreservation:
    def test_canonical_append_preserves_ks(self, tmp_path):
        env = _env(ks=["quant-theory"])
        store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
        store.append(env)
        line = json.loads((tmp_path / "events-v1.jsonl").read_text().splitlines()[0])
        assert line["knowledge_space_ids"] == ["quant-theory"]


class TestC1FollowupContract:
    """C1 follow-up (review): production adapter edge cases + strict typing."""

    @staticmethod
    def _prod_envelope(sanitized: dict):
        from types import SimpleNamespace
        from src.integration import capture_adapter
        mapped = SimpleNamespace(source="hermes", event_type="user_statement",
                                 hook="pre_tool_call")
        return capture_adapter._envelope(mapped, sanitized)

    # P1-1: string multi must be REJECTED (fail-closed), not char-split.
    def test_prod_rejects_string_multi(self):
        with pytest.raises(ValueError):
            self._prod_envelope({"text": "hi", "knowledge_space_ids": "AB"})

    # P1-2: empty multi + valid legacy -> legacy list (ADR §2).
    def test_prod_empty_multi_plus_legacy_uses_legacy(self):
        env = self._prod_envelope({
            "text": "hi", "knowledge_space_ids": [],
            "knowledge_space_id": "legacy-ks"})
        assert env["knowledge_space_ids"] == ["legacy-ks"]

    # P1-2: absent multi + valid legacy -> legacy list.
    def test_prod_absent_multi_plus_legacy_uses_legacy(self):
        env = self._prod_envelope({"text": "hi", "knowledge_space_id": "legacy-ks"})
        assert env["knowledge_space_ids"] == ["legacy-ks"]

    # P1-2: malformed multi + legacy -> REJECT (fail-closed, not silent fallback).
    def test_prod_malformed_multi_plus_legacy_rejected(self):
        with pytest.raises(ValueError):
            self._prod_envelope({
                "text": "hi", "knowledge_space_ids": "AB",
                "knowledge_space_id": "legacy-ks"})

    # P1-2: empty legacy -> rejected/omitted (not a one-char list).
    def test_prod_empty_legacy_not_accepted(self):
        env = self._prod_envelope({"text": "hi", "knowledge_space_id": "  "})
        assert "knowledge_space_ids" not in env

    # P2-3: payload explicit None wins over param and OMITS.
    def test_normalize_payload_none_wins_and_omits(self):
        env = _env(ks=["PARAM"])
        # re-run normalize_event with payload carrying explicit None
        env2 = normalize_event(
            {"text": "hi", "redaction_audit": _AUDIT, "knowledge_space_ids": None},
            profile_id="p1", project_id="P", sequence=0,
            event_type="user_statement", source="hermes_chat",
            knowledge_space_ids=["PARAM"])
        assert "knowledge_space_ids" not in env2

    # P2-4: payload list wins over param.
    def test_normalize_payload_list_wins_over_param(self):
        env = normalize_event(
            {"text": "hi", "redaction_audit": _AUDIT,
             "knowledge_space_ids": ["PAYLOAD"]},
            profile_id="p1", project_id="P", sequence=0,
            event_type="user_statement", source="hermes_chat",
            knowledge_space_ids=["PARAM"])
        assert env["knowledge_space_ids"] == ["PAYLOAD"]

    # P2-4: payload [] wins over param.
    def test_normalize_payload_empty_wins_over_param(self):
        env = normalize_event(
            {"text": "hi", "redaction_audit": _AUDIT,
             "knowledge_space_ids": []},
            profile_id="p1", project_id="P", sequence=0,
            event_type="user_statement", source="hermes_chat",
            knowledge_space_ids=["PARAM"])
        assert env["knowledge_space_ids"] == []

    # P2-4: tuple multi rejected by validation (strict List[str]).
    def test_validation_rejects_tuple(self):
        env = _env(ks=["A"])
        env["knowledge_space_ids"] = ("A", "B")
        with pytest.raises(ValueError):
            validate_envelope(env)
