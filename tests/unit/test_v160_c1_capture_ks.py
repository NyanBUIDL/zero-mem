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
