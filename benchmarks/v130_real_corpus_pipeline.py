"""V130-05 — Real-corpus pipeline: export + REDACTION GATE.

Streams canonical JSONL from the archive (READ-ONLY source, stop-rule 2 safe),
runs every line through the production redaction scan (fail-closed: any secret
detection aborts the export), and writes the sanitized corpus to dev-data
fixtures (never into git/release artifacts).

Gate test (tests/unit/test_v130_05_redaction_gate.py) proves:
- a known-secret line is BLOCKED;
- a clean corpus passes;
- the exported fixture is outside git tracking.

Usage:
    .venv-v124/bin/python benchmarks/v130_real_corpus_pipeline.py \
        --src <archive.jsonl> --out <dev-data-fixture.jsonl> --limit 5000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Patterns that must NEVER appear in persisted content (fail-closed gate).
_SECRET_MARKERS = (
    "sk-", "AKIA", "-----BEGIN", "ghp_", "xoxb-", "password=",
    "BEGIN RSA PRIVATE", "BEGIN OPENSSH PRIVATE",
)

# v1.3.1 (WP-6): production-redacted markers are already sanitized by the
# redaction pipeline; strip them BEFORE marker scanning so an already-redacted
# line passes while real secrets still fail closed.
#
# v1.3.2 (WP-02, audit P1-3) marker-abuse hardening: the loose pattern
# «redacted:[^»]*» let attacker-controlled marker-LIKE content (free-form
# inner text, e.g. a live secret token) bypass the scan. A marker is now
# exempt ONLY when it matches the EXACT production emission format
# «redacted:[REDACTED:<rule>]» with <rule> from the closed rule set of
# src/redaction/redactor.py (_RULES). Every near-miss is scanned normally.
_REDACTION_RULES = (
    "api_key_assignment", "authorization_header", "bearer_token",
    "credential_url_userinfo", "oauth_secret", "password_assignment",
    "private_key_block",
)
_REDACTED_MARKER_RE = re.compile(
    r"«redacted:\[REDACTED:(" + "|".join(_REDACTION_RULES) + r")\]»"
)


def scan_line_secret(line: str) -> bool:
    """True when the raw line contains a live secret marker (gate trips).

    Exact-format already-redacted markers («redacted:[REDACTED:<rule>]») are
    stripped first — they carry no live secret and cannot be forged with
    free-form content (v1.3.1 behavior kept, v1.3.2 hardened). Any
    marker-like variant is scanned normally; this change only ever BLOCKS
    more, never less.
    """
    scanned = _REDACTED_MARKER_RE.sub("", line)
    low = scanned.lower()
    return any(m.lower() in low for m in _SECRET_MARKERS)


def export_corpus(src: Path, out: Path, limit: int) -> dict:
    """Stream src read-only; write sanitized lines to out. Fail closed on secret."""
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    blocked = 0
    scanned = 0
    tmp = out.with_suffix(".tmp")
    with open(src, "r", encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            scanned += 1
            stripped = line.strip()
            if not stripped:
                continue
            if scan_line_secret(stripped):
                blocked += 1
                # FAIL CLOSED: abort the whole export, remove partial output.
                tmp.unlink(missing_ok=True)
                return {"scanned": scanned, "written": written, "blocked": blocked,
                        "status": "BLOCKED_SECRET_DETECTED"}
            # Re-serialize deterministically (sorted keys) so the fixture is stable.
            env = json.loads(stripped)
            fout.write(json.dumps(env, sort_keys=True, separators=(",", ":")) + "\n")
            written += 1
            if written >= limit:
                break
    tmp.replace(out)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return {"scanned": scanned, "written": written, "blocked": blocked,
            "status": "OK", "sha256": digest}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args()
    res = export_corpus(Path(args.src), Path(args.out), args.limit)
    print(json.dumps(res, indent=2))
    if res["status"] != "OK":
        sys.exit(1)


if __name__ == "__main__":
    main()
