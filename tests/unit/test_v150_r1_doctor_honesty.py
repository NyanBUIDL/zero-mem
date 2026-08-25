"""V150-R1 — doctor honesty after canonical-first (DEF-019).

The doctor check ``corpus_authorization`` was written for the DEF-012/015
resolver era. Since V150-WP2/WP3 the event path authorizes per-row via
``zm_meta.knowledge_space_id`` and NEVER consults a corpus store, so:

- Unconfigured corpus store must NOT warn that space grants are
  "non-authorizing" — they work without any corpus store.
- The check must not instruct users to set ``corpus-store-path`` in order to
  make event-path space grants work (that store only serves
  ``corpus_unit_search``).
"""

from __future__ import annotations

import json

from tests.unit.test_v141_r2_remediation import isolated_env  # noqa: F401


def _doctor_payload(capsys) -> list[dict]:
    from zero_mem import commands_doctor

    commands_doctor.run(as_json=True)
    out = capsys.readouterr().out
    data = json.loads(out)
    return [c for c in data.get("checks", []) if c["id"] == "corpus_authorization"]


class TestDef019DoctorHonestyCanonicalFirst:
    def test_unconfigured_does_not_claim_event_grants_dead(
            self, isolated_env, capsys):
        """Unconfigured corpus store: the message must not say space grants
        are non-authorizing, nor prescribe corpus-store-path as the fix."""
        checks = _doctor_payload(capsys)
        assert checks, "doctor must surface corpus_authorization"
        message = str(checks[0].get("message", ""))
        assert "non-authorizing" not in message, (
            "DEF-019: doctor must not claim space grants are non-authorizing "
            "without a corpus store — event-path authorization is per-row via "
            "zm_meta.knowledge_space_id")
        assert "config set" not in message or "corpus_unit_search" in message, (
            "doctor must not prescribe corpus-store-path as an event-path fix")

    def test_message_describes_canonical_first_mechanism(
            self, isolated_env, capsys):
        checks = _doctor_payload(capsys)
        message = str(checks[0].get("message", "")).lower()
        assert ("per-row" in message) or ("zm_meta" in message), (
            "corpus_authorization message must describe per-row canonical "
            "authorization (zm_meta.knowledge_space_id)")
