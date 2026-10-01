"""DEF-049: pre-register secret scan helper (``src.redaction.prescan``).

Used BEFORE a blob is stored so rejected content never reaches the blob store. Synthetic
credentials are assembled at runtime; nothing here is a real secret.
"""
from __future__ import annotations

import codecs

import pytest

from src.redaction import RedactionRejected
from src.redaction.prescan import (
    PrescanRejected,
    assert_bytes_safe,
    assert_text_safe,
    scan_bytes,
    scan_text,
)

GHP = "gh" + "p_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
ANT = "sk-" + "ant-api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2" + "XyZ"
CLEAN = "Alice prefers PostgreSQL for storage.\n\nDeploy staging on fly.io every Friday.\n"
SECRET_DOC = f"# notes\n\nthe deploy token is {GHP} (do not share)\n"


def test_scan_text_clean_and_dirty():
    ok = scan_text(CLEAN)
    assert ok.safe and ok.rule_ids == () and ok.reason is None
    bad = scan_text(SECRET_DOC)
    assert not bad.safe and "vendor_api_token" in bad.rule_ids
    assert bad.reason == "secret_detected"


def test_assert_text_safe_returns_none_when_clean_and_raises_when_not():
    assert assert_text_safe(CLEAN) is None
    with pytest.raises(PrescanRejected) as exc:
        assert_text_safe(SECRET_DOC)
    assert isinstance(exc.value, RedactionRejected) and isinstance(exc.value, ValueError)
    message = str(exc.value)
    assert GHP not in message and "ghp_" not in message
    assert "secret_detected" in message and "vendor_api_token" in message


def test_results_and_errors_never_contain_the_secret():
    for result in (scan_text(SECRET_DOC), scan_bytes(SECRET_DOC.encode())):
        assert GHP not in repr(result) and GHP not in str(result)
    with pytest.raises(PrescanRejected) as exc:
        assert_bytes_safe(SECRET_DOC.encode())
    assert GHP not in repr(exc.value) and GHP not in str(exc.value.args)


@pytest.mark.parametrize("payload", [
    pytest.param(SECRET_DOC.encode("utf-8"), id="utf8"),
    pytest.param(codecs.BOM_UTF8 + SECRET_DOC.encode("utf-8"), id="utf8-bom"),
    pytest.param(codecs.BOM_UTF16_LE + SECRET_DOC.encode("utf-16-le"), id="utf16-le-bom"),
    pytest.param(codecs.BOM_UTF16_BE + SECRET_DOC.encode("utf-16-be"), id="utf16-be-bom"),
    pytest.param(SECRET_DOC.encode("utf-16-le"), id="utf16-le-no-bom"),
    pytest.param(SECRET_DOC.encode("utf-16-be"), id="utf16-be-no-bom"),
    pytest.param(codecs.BOM_UTF32_LE + SECRET_DOC.encode("utf-32-le"), id="utf32-le-bom"),
    pytest.param(SECRET_DOC.encode("latin-1", "replace") + b"\xe9\xe8\xff", id="latin1-tail"),
    pytest.param(b"\x80\x81\x82binary\x00\x01" + f" {ANT} ".encode() + b"\xfe\xfd\x00", id="binary-with-ascii-secret"),
    pytest.param(b"\xff\xfe\x00" + SECRET_DOC.encode() + b"\x00\xff", id="garbage-around-secret"),
])
def test_scan_bytes_detects_secret_across_encodings(payload):
    result = scan_bytes(payload)
    assert not result.safe
    assert result.rule_ids
    with pytest.raises(PrescanRejected):
        assert_bytes_safe(payload)


@pytest.mark.parametrize("payload", [
    b"",
    CLEAN.encode("utf-8"),
    codecs.BOM_UTF8 + CLEAN.encode("utf-8"),
    codecs.BOM_UTF16_LE + CLEAN.encode("utf-16-le"),
    CLEAN.encode("utf-16-le"),
    "Toi thich ca phe sua da. Mat khau luu trong kho.".encode("utf-8"),
    "Tôi thích cà phê sữa đá.".encode("utf-8"),
    "Tôi thích cà phê sữa đá.".encode("utf-16"),
    bytes(range(256)) * 4,   # arbitrary binary, no credential shapes
])
def test_scan_bytes_clean_inputs_are_safe(payload):
    result = scan_bytes(payload)
    assert result.safe and result.rule_ids == ()
    assert assert_bytes_safe(payload) is None


def test_scan_bytes_accepts_bytearray_and_memoryview_and_rejects_str():
    assert scan_bytes(bytearray(SECRET_DOC.encode())).safe is False
    assert scan_bytes(memoryview(CLEAN.encode())).safe is True
    with pytest.raises(TypeError):
        scan_bytes(CLEAN)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scan_text(CLEAN.encode())  # type: ignore[arg-type]


def test_pem_block_and_env_assignment_detected_in_bytes():
    pem = b"-----BEGIN PRIVATE KEY-----\nQUJDREVGRw==\n-----END PRIVATE KEY-----\n"
    assert not scan_bytes(pem).safe
    assert not scan_bytes(b"export GITHUB_TOKEN=abcdef1234567890\n").safe
    # malformed (truncated) PEM fails closed rather than raising
    truncated = scan_bytes(b"-----BEGIN PRIVATE KEY-----\ntruncated")
    assert not truncated.safe


def test_scan_is_pure_and_repeatable():
    data = SECRET_DOC.encode()
    before = bytes(data)
    assert scan_bytes(data) == scan_bytes(data)
    assert data == before


def test_notes_store_reuses_central_redactor(tmp_path):
    from zero_mem import notes
    from zero_mem.notes import NotesStore

    assert not hasattr(notes, "_VENDOR_SECRET"), "notes.py must reuse src.redaction, not its own regex"
    store = NotesStore(tmp_path / "n.jsonl", tmp_path / "n.sqlite3")
    extra = [
        "hf" + "_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"[:34],
        "sk" + "_live_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
        "export GITHUB_TOKEN=abcdef1234567890",
        "connect postgres://admin:s3cretpw@db.internal:5432/app now",
    ]
    for text in extra:
        assert store.add_text(f"remember {text} for later")["rejected_secret"] == 1, text
    assert store.count() == 0
    assert store.add_text("Alice prefers PostgreSQL.")["added"] == 1
