"""Closed-schema wire formats of the sharing protocol (ADR-V170-05, section 6/7).

Every parser here is strict: bytes -> JSON (no duplicate keys, no NaN/Infinity, bounded nesting) -> exact key sets and types.
They are used both by the server (requests from peers) and by the client (responses from owners: a malicious owner is
as untrusted as a malicious peer). Failures raise :class:`~zero_mem.share.ShareError` with a fixed code, never the offending value.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote

from . import PROTOCOL_VERSION, ShareError
from .util import FP_RE, PEER_ID_RE

MAX_MANIFEST_ENTRIES = 1000
MAX_FETCH_IDS = 50
MAX_TOMBSTONES = 1000
MAX_REF_CHARS = 400
_SEGMENT = r"[A-Za-z0-9._:~+@%-]+"
REF_RE = re.compile(rf"^(mem|file)://{_SEGMENT}(?:/{_SEGMENT})*$")
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{4,128}$")
KIND_RE = re.compile(r"^[a-z0-9]{1,16}$")
DIGEST_RE = FP_RE
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
MEMORY_TYPES = ("persona", "workflow", "skill", "devlog", "fact", "file", "rule", "decision", "gotcha")
LEARNED_TYPES = ("rule", "decision", "gotcha")


def _no_dupes(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _bad_constant(_name: str):
    raise ValueError("non-finite number")


def load_json(data: bytes, *, max_bytes: int, what: str = "message") -> Any:
    if not isinstance(data, (bytes, bytearray)) or len(data) > max_bytes:
        raise ShareError("invalid_message", f"{what} is too large")
    try:
        return json.loads(bytes(data).decode("utf-8"), object_pairs_hook=_no_dupes, parse_constant=_bad_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ShareError("invalid_message", f"{what} is not valid JSON") from None


def dump_json(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _closed(doc: Any, keys: set, what: str) -> dict:
    if not isinstance(doc, dict) or set(doc) != keys:
        raise ShareError("invalid_message", f"{what} has an unexpected shape")
    return doc


def _int(value: Any, low: int, high: int, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ShareError("invalid_message", f"{what} is out of range")
    return value


def _str(value: Any, limit: int, what: str, *, low: int = 1) -> str:
    if not isinstance(value, str) or not low <= len(value) <= limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ShareError("invalid_message", f"{what} is invalid")
    return value


# ---------------------------------------------------------------------------------------------
# references
# ---------------------------------------------------------------------------------------------
def check_ref(ref: Any) -> tuple:
    """Validate an ``external_ref`` from a peer: ``(scheme, memory_type, rest)`` or raise ``unsafe_ref``.

    Grammar: ``mem://<type>/<name...>`` or ``file://<name...>``; segments use the ref alphabet only (no ``.``/``..``, no
    separators or control characters, also after percent-decoding); at most 400 characters."""
    bad = ShareError("unsafe_ref", "a reference from the peer is not acceptable")
    if not isinstance(ref, str) or len(ref) > MAX_REF_CHARS or not REF_RE.fullmatch(ref):
        raise bad
    scheme, _, rest = ref.partition("://")
    for segment in rest.split("/"):
        if segment in (".", ".."):
            raise bad
        decoded = unquote(segment)
        if decoded in (".", "..") or any(c in decoded for c in "/\\\x00") or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
            raise bad
    if scheme == "file":
        return scheme, "file", rest
    mtype, _, name = rest.partition("/")
    if mtype not in MEMORY_TYPES or mtype == "file" or not name:
        raise bad
    return scheme, mtype, name


# ---------------------------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------------------------
ENTRY_KEYS = {"source_id", "ref", "memory_type", "kind", "version", "digest", "size", "updated_at"}


def parse_entry(raw: Any, *, max_source_bytes: int) -> dict:
    entry = _closed(raw, ENTRY_KEYS, "a manifest entry")
    sid = entry["source_id"]
    if not isinstance(sid, str) or not SOURCE_ID_RE.fullmatch(sid):
        raise ShareError("invalid_message", "source_id is invalid")
    scheme, mtype, _rest = check_ref(entry["ref"])
    if entry["memory_type"] != mtype:
        raise ShareError("unsafe_ref", "reference and memory type disagree")
    if not isinstance(entry["kind"], str) or not KIND_RE.fullmatch(entry["kind"]):
        raise ShareError("invalid_message", "kind is invalid")
    _str(entry["version"], 128, "version")
    if not isinstance(entry["digest"], str) or not DIGEST_RE.fullmatch(entry["digest"]):
        raise ShareError("invalid_message", "digest is invalid")
    _int(entry["size"], 0, 1 << 40, "size")
    if not isinstance(entry["updated_at"], str) or not TS_RE.fullmatch(entry["updated_at"]):
        raise ShareError("invalid_message", "updated_at is invalid")
    return dict(entry)


def parse_manifest(data: bytes, *, max_bytes: int = 4 << 20) -> dict:
    """``{"entries": [valid...], "rejected": [{"index", "code"}...], "omitted": {...}}`` from an owner's manifest."""
    doc = _closed(load_json(data, max_bytes=max_bytes, what="the manifest"),
                  {"v", "peer_id", "generated_at", "sources", "omitted"}, "the manifest")
    if doc["v"] != PROTOCOL_VERSION:
        raise ShareError("invalid_message", "unsupported protocol version")
    if not isinstance(doc["peer_id"], str) or not PEER_ID_RE.fullmatch(doc["peer_id"]):
        raise ShareError("invalid_message", "peer_id is invalid")
    if not isinstance(doc["sources"], list) or len(doc["sources"]) > MAX_MANIFEST_ENTRIES:
        raise ShareError("invalid_message", "the manifest has too many entries")
    omitted = doc["omitted"]
    if not isinstance(omitted, dict) or len(omitted) > 16 or any(
            not isinstance(k, str) or len(k) > 40 or not isinstance(v, int) or isinstance(v, bool) or v < 0
            for k, v in omitted.items()):
        raise ShareError("invalid_message", "omitted is invalid")
    entries, rejected, seen = [], [], set()
    for index, raw in enumerate(doc["sources"]):
        try:
            entry = parse_entry(raw, max_source_bytes=0)
            if entry["source_id"] in seen:
                raise ShareError("invalid_message", "duplicate source")
            seen.add(entry["source_id"])
            entries.append(entry)
        except ShareError as exc:
            rejected.append({"index": index, "code": exc.code})
    return {"entries": entries, "rejected": rejected, "omitted": dict(omitted)}


# ---------------------------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------------------------
def parse_fetch_request(data: bytes) -> list:
    doc = _closed(load_json(data, max_bytes=64 * 1024, what="the request"), {"v", "source_ids"}, "the request")
    if doc["v"] != PROTOCOL_VERSION:
        raise ShareError("invalid_message", "unsupported protocol version")
    ids = doc["source_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_FETCH_IDS:
        raise ShareError("invalid_message", "source_ids must list 1 to %d ids" % MAX_FETCH_IDS)
    out = []
    for sid in ids:
        if not isinstance(sid, str) or not SOURCE_ID_RE.fullmatch(sid):
            raise ShareError("invalid_message", "source_id is invalid")
        if sid not in out:
            out.append(sid)
    return out


FETCHED_KEYS = ENTRY_KEYS | {"content_b64"}


def parse_fetch_response(data: bytes, *, max_bytes: int) -> dict:
    """``{"sources": [entry+content_b64 ...], "missing": [...], "deferred": [...]}`` (content still base64: the caller decodes)."""
    doc = _closed(load_json(data, max_bytes=max_bytes, what="the fetch response"),
                  {"v", "sources", "missing", "deferred"}, "the fetch response")
    if doc["v"] != PROTOCOL_VERSION:
        raise ShareError("invalid_message", "unsupported protocol version")
    if not isinstance(doc["sources"], list) or len(doc["sources"]) > MAX_FETCH_IDS:
        raise ShareError("invalid_message", "too many sources")
    sources = []
    for raw in doc["sources"]:
        raw = _closed(raw, FETCHED_KEYS, "a fetched source")
        entry = parse_entry({k: raw[k] for k in ENTRY_KEYS}, max_source_bytes=0)
        if not isinstance(raw["content_b64"], str):
            raise ShareError("invalid_message", "content is invalid")
        entry["content_b64"] = raw["content_b64"]
        sources.append(entry)
    for key in ("missing", "deferred"):
        if not isinstance(doc[key], list) or len(doc[key]) > MAX_FETCH_IDS or any(
                not isinstance(s, str) or not SOURCE_ID_RE.fullmatch(s) for s in doc[key]):
            raise ShareError("invalid_message", f"{key} is invalid")
    return {"sources": sources, "missing": list(doc["missing"]), "deferred": list(doc["deferred"])}


# ---------------------------------------------------------------------------------------------
# tombstones
# ---------------------------------------------------------------------------------------------
def parse_tombstones(data: bytes, *, max_bytes: int = 1 << 20) -> dict:
    doc = _closed(load_json(data, max_bytes=max_bytes, what="the tombstone list"),
                  {"v", "tombstones", "until", "more"}, "the tombstone list")
    if doc["v"] != PROTOCOL_VERSION or not isinstance(doc["more"], bool):
        raise ShareError("invalid_message", "unsupported protocol version")
    if not isinstance(doc["until"], str) or not TS_RE.fullmatch(doc["until"]):
        raise ShareError("invalid_message", "until is invalid")
    if not isinstance(doc["tombstones"], list) or len(doc["tombstones"]) > MAX_TOMBSTONES:
        raise ShareError("invalid_message", "too many tombstones")
    out, rejected = [], 0
    for raw in doc["tombstones"]:
        try:
            raw = _closed(raw, {"source_id", "ref", "memory_type", "forgotten_at"}, "a tombstone")
            if not isinstance(raw["source_id"], str) or not SOURCE_ID_RE.fullmatch(raw["source_id"]):
                raise ShareError("invalid_message", "source_id is invalid")
            _s, mtype, _r = check_ref(raw["ref"])
            if raw["memory_type"] != mtype or not isinstance(raw["forgotten_at"], str) or not TS_RE.fullmatch(raw["forgotten_at"]):
                raise ShareError("invalid_message", "tombstone is invalid")
            out.append(dict(raw))
        except ShareError:
            rejected += 1
    return {"tombstones": out, "rejected": rejected, "until": doc["until"], "more": doc["more"]}


# ---------------------------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------------------------
def parse_pair_request(data: bytes) -> dict:
    doc = _closed(load_json(data, max_bytes=8 * 1024, what="the pairing request"),
                  {"v", "token", "cert_der_b64", "label"}, "the pairing request")
    if doc["v"] != PROTOCOL_VERSION:
        raise ShareError("invalid_message", "unsupported protocol version")
    _str(doc["token"], 128, "token", low=16)
    _str(doc["cert_der_b64"], 4096, "certificate", low=100)
    _str(doc["label"], 40, "label")
    return dict(doc)


def parse_pair_response(data: bytes) -> dict:
    doc = _closed(load_json(data, max_bytes=8 * 1024, what="the pairing response"),
                  {"v", "status", "peer_id", "label", "service_port"}, "the pairing response")
    if doc["v"] != PROTOCOL_VERSION or doc["status"] != "paired" or not isinstance(doc["peer_id"], str) \
            or not PEER_ID_RE.fullmatch(doc["peer_id"]):
        raise ShareError("pairing_failed", "the owner did not accept the pairing")
    _str(doc["label"], 40, "label")
    _int(doc["service_port"], 1, 65535, "service_port")
    return dict(doc)
