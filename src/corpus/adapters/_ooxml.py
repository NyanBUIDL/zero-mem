"""Shared, defensive OOXML (docx/xlsx/pptx) container helpers (stdlib only).

Office files are untrusted zip archives full of XML, so every read goes through
explicit guards (design section 2: "Zip inputs need uncompressed-size and entry caps"):

- entry-count cap and total *declared* uncompressed-size cap (zip bomb),
- per-member read cap enforced while reading (a lying header cannot exceed it),
- DTD / entity declarations are refused outright (OOXML never needs them), which
  closes billion-laughs and XXE vectors regardless of the expat build,
- nothing is ever extracted to disk (member names are only dictionary keys),
- every failure is an :class:`OoxmlError` carrying a safe, content-free reason.
"""
from __future__ import annotations

import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Iterator, Optional

DEFAULT_MAX_ENTRIES = 10_000
DEFAULT_MAX_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES = 48 * 1024 * 1024


class OoxmlError(Exception):
    """A typed container/XML failure. ``str(exc)`` is safe to surface as ``error_reason``."""


def local(tag: str) -> str:
    """Local name of a Clark-notation tag (``{ns}p`` -> ``p``); works for strict and transitional OOXML."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def attr(elem: ET.Element, name: str, *, namespaced: bool = False) -> Optional[str]:
    """Attribute by local name (``w:val`` / ``r:id`` / plain), namespace-agnostic.

    ``namespaced=True`` matches only prefixed attributes (``r:id`` but not a plain ``id``),
    needed where both exist on one element (``<p:sldId id="256" r:id="rId2"/>``).
    """
    for key, value in elem.attrib.items():
        if key.endswith("}" + name) or (not namespaced and key == name):
            return value
    return None


def declared_entry_count(content: bytes) -> Optional[int]:
    """Entry count declared in the end-of-central-directory record, read *without* building
    the ``ZipInfo`` list (so a hostile archive with millions of entries is refused cheaply).
    ``None`` if there is no classic EOCD record or it is zip64 (``0xFFFF`` = see zip64 record)."""
    tail = content[-(65_535 + 22):]
    idx = tail.rfind(b"PK\x05\x06")
    if idx < 0 or len(tail) - idx < 22:
        return None
    total = int.from_bytes(tail[idx + 10:idx + 12], "little")
    return None if total == 0xFFFF else total


def open_package(
    content: bytes,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED,
) -> zipfile.ZipFile:
    declared = declared_entry_count(content)
    if declared is not None and declared > max_entries:
        raise OoxmlError(f"zip bomb guard: {declared} entries exceed cap {max_entries}")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
        infos = zf.infolist()
    except Exception as exc:  # BadZipFile, NotImplementedError, struct.error, ...
        raise OoxmlError(f"not a readable zip container ({type(exc).__name__})") from None
    if len(infos) > max_entries:
        raise OoxmlError(f"zip bomb guard: {len(infos)} entries exceed cap {max_entries}")
    total = sum(max(i.file_size, 0) for i in infos)
    if total > max_total_uncompressed:
        raise OoxmlError(
            f"zip bomb guard: total uncompressed size {total} exceeds cap {max_total_uncompressed}"
        )
    return zf


def has_member(zf: zipfile.ZipFile, name: str) -> bool:
    try:
        zf.getinfo(name)
        return True
    except KeyError:
        return False


def read_member(zf: zipfile.ZipFile, name: str, *, max_bytes: int) -> bytes:
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise OoxmlError(f"missing package member {name}") from None
    if info.file_size > max_bytes:
        raise OoxmlError(f"zip bomb guard: member {name} ({info.file_size} bytes) exceeds cap {max_bytes}")
    if info.flag_bits & 0x1:
        raise OoxmlError(f"member {name} is encrypted")
    try:
        with zf.open(info) as fh:
            data = fh.read(max_bytes + 1)
    except Exception as exc:  # zlib.error, BadZipFile (CRC), RuntimeError, ...
        raise OoxmlError(f"member {name} unreadable ({type(exc).__name__})") from None
    if len(data) > max_bytes:
        raise OoxmlError(f"zip bomb guard: member {name} exceeds cap {max_bytes}")
    return data


def check_xml_bytes(data: bytes, name: str) -> None:
    """Refuse DTDs/entities and non-UTF-8 XML (UTF-16 parts would dodge the byte scan)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:64]:
        raise OoxmlError(f"{name}: unsupported xml encoding")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise OoxmlError(f"{name}: dtd/entity declarations are not allowed")


def parse_xml(data: bytes, name: str) -> ET.Element:
    check_xml_bytes(data, name)
    try:
        return ET.fromstring(data)
    except Exception as exc:  # ParseError, RecursionError, ValueError
        raise OoxmlError(f"{name}: invalid xml ({type(exc).__name__})") from None


def iterparse_xml(data: bytes, name: str, events=("end",)) -> Iterator[tuple[str, ET.Element]]:
    """Streaming parse; raises :class:`OoxmlError` on malformed XML (also mid-iteration)."""
    check_xml_bytes(data, name)
    try:
        for item in ET.iterparse(io.BytesIO(data), events=events):
            yield item
    except OoxmlError:
        raise
    except Exception as exc:
        raise OoxmlError(f"{name}: invalid xml ({type(exc).__name__})") from None


def resolve_target(base_dir: str, target: str) -> str:
    """Resolve a relationship ``Target`` against the part directory it is relative to."""
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(base_dir, target))


def read_relationships(zf: zipfile.ZipFile, rels_name: str, base_dir: str, *, max_bytes: int) -> dict[str, str]:
    """``{rId: resolved part name}`` from a ``.rels`` part (empty if absent or unreadable)."""
    if not has_member(zf, rels_name):
        return {}
    try:
        root = parse_xml(read_member(zf, rels_name, max_bytes=max_bytes), rels_name)
    except OoxmlError:
        return {}
    out: dict[str, str] = {}
    for rel in root:
        if local(rel.tag) != "Relationship":
            continue
        rid, target = rel.attrib.get("Id"), rel.attrib.get("Target")
        if rid and target and rel.attrib.get("TargetMode") != "External":
            out[rid] = resolve_target(base_dir, target)
    return out


_NATURAL = re.compile(r"(\d+)")


def natural_key(name: str) -> list:
    return [int(p) if p.isdigit() else p for p in _NATURAL.split(name)]


__all__ = [
    "DEFAULT_MAX_ENTRIES", "DEFAULT_MAX_TOTAL_UNCOMPRESSED", "DEFAULT_MAX_MEMBER_BYTES",
    "OoxmlError", "declared_entry_count", "local", "attr", "open_package", "has_member", "read_member",
    "check_xml_bytes", "parse_xml", "iterparse_xml", "resolve_target", "read_relationships",
    "natural_key",
]
