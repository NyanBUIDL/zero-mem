"""V132-02 — Redaction-gate marker-abuse hardening (audit P1-3).

v1.3.1 WP-6 let already-redacted lines through the gate by stripping
``«redacted:…»`` before the secret scan. That opening allowed attacker-
controlled marker-LIKE content («redacted:<anything», including a live
secret token as free-form inner text) to bypass the scan.

v1.3.2 semantics (fail-closed, blocks MORE, never less):
  * A marker is ONLY exempted from scanning when it matches the EXACT
    production format ``«redacted:[REDACTED:<rule>]»`` where <rule> is one
    of the closed rule set emitted by src/redaction/redactor.py (_RULES).
  * Every near-miss (case change, spacing, extra free-form text, unknown
    rule) is scanned normally.
  * A live secret anywhere else on the line still trips the gate.

Cases:
  (a) exact-format marker            -> passes the gate (v1.3.1 behavior kept)
  (b) marker + free-form secret text -> BLOCKED (was: bypassed)
  (c) marker-like variants           -> scanned normally (blocked iff secret)
  (d) plain secret, no marker        -> blocked (regression guard unchanged)

Evidence: zero-mem-dev-data/evidence/v132/wp2-{red,green,full-suite}.log
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.v130_real_corpus_pipeline import scan_line_secret


class TestV132Wp2MarkerAbuse:
    def test_a_exact_format_marker_passes(self):
        line = ('{"sanitized_content": {"text": "key '
                '«redacted:[REDACTED:api_key_assignment]» ok"}}')
        assert not scan_line_secret(line)

    def test_a_exact_format_all_rules_pass(self):
        for rule in ("authorization_header", "bearer_token", "oauth_secret",
                     "password_assignment", "private_key_block",
                     "credential_url_userinfo"):
            line = f'{{"t": "x «redacted:[REDACTED:{rule}]» y"}}'
            assert not scan_line_secret(line), rule

    def test_b_free_form_inner_secret_blocked(self):
        # v1.3.1 hole: free-form inner text was stripped unscanned.
        line = '{"sanitized_content": {"text": "key «redacted:sk-live1234» ok"}}'
        assert scan_line_secret(line)

    def test_b_exact_marker_plus_live_secret_outside_still_blocked(self):
        line = ('{"t": "old «redacted:[REDACTED:bearer_token]» ", '
                '"note": "live ghp_ABCDEF"}')
        assert scan_line_secret(line)

    def test_c_case_variant_is_scanned(self):
        # Case change => near-miss => normal scan; contains a secret -> block.
        line = '{"t": "«Redacted:[REDACTED:api_key_assignment]» sk-live1"}'
        assert scan_line_secret(line)
        # Same variant WITHOUT a secret behaves as ordinary text -> passes.
        clean = '{"t": "«Redacted:[REDACTED:api_key_assignment]» nothing here"}'
        assert not scan_line_secret(clean)

    def test_c_spacing_and_extra_text_variants_are_scanned(self):
        variants_with_secret = (
            '{"t": "«redacted: [REDACTED:api_key_assignment]» sk-live9"}',
            '{"t": "«redacted:[REDACTED: api_key_assignment]» sk-live9"}',
            '{"t": "«redacted:[REDACTED:api_key_assignment] extra» sk-live9"}',
            '{"t": "«redacted:[REDACTED:not_a_rule]» sk-live9"}',
        )
        for line in variants_with_secret:
            assert scan_line_secret(line), line

    def test_c_clean_variant_text_passes(self):
        line = '{"t": "see «redacted:[REDACTED:not_a_rule]» documentation"}'
        assert not scan_line_secret(line)

    def test_d_plain_secret_blocked_regression(self):
        assert scan_line_secret('{"t": "key sk-live1234"}')
        assert scan_line_secret('{"t": "-----BEGIN RSA PRIVATE"}')

    def test_d_multiple_markers_mixed(self):
        # One exact marker (exempt) + one abusive marker carrying a secret.
        line = ('{"t": "ok «redacted:[REDACTED:bearer_token]» and '
                '«redacted:xoxb-REALTOKEN»"}')
        assert scan_line_secret(line)
