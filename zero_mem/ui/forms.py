"""Request body parsing for the control panel: urlencoded forms and a small, strict multipart/form-data parser.

Standard library only (``cgi`` is gone in Python 3.13). Everything here is bounded: field counts, header sizes, part
sizes. A malformed body raises :class:`FormError`; the caller turns that into a generic 400.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from email.parser import BytesHeaderParser
from typing import Optional
from urllib.parse import parse_qsl

MAX_FIELDS = 100
MAX_PARTS = 20
MAX_PART_HEADER_BYTES = 8 * 1024
MAX_BOUNDARY_CHARS = 70
MAX_FILENAME_CHARS = 255
_BOUNDARY_RE = re.compile(r"^[0-9A-Za-z'()+_,\-./:=? ]{1,70}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class FormError(ValueError):
    """The request body is not a well-formed form (the message is a fixed, safe string)."""


@dataclass(frozen=True)
class Upload:
    filename: str
    content: bytes


class FormData(dict):
    """Text fields (first value wins) plus every submitted value per name via :meth:`getlist`."""

    def __init__(self) -> None:
        super().__init__()
        self._lists: dict = {}

    def add(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)
        self.setdefault(key, value)

    def getlist(self, key: str) -> list:
        return list(self._lists.get(key, []))


def parse_urlencoded(body: bytes) -> FormData:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise FormError("form is not valid UTF-8") from None
    try:
        pairs = parse_qsl(text, keep_blank_values=True, max_num_fields=MAX_FIELDS, encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise FormError("form could not be parsed") from None
    out = FormData()
    for key, value in pairs:
        out.add(key, value)  # the first value wins for scalar fields; checkboxes read getlist()
    return out


def _boundary_of(content_type: str) -> str:
    match = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', content_type, re.IGNORECASE)
    if not match:
        raise FormError("multipart boundary missing")
    boundary = match.group(1) or match.group(2)
    if not _BOUNDARY_RE.match(boundary) or boundary.endswith(" "):
        raise FormError("multipart boundary invalid")
    return boundary


def safe_upload_name(name: Optional[str]) -> str:
    """The client's file name, or :class:`FormError` when it carries a path component or odd characters."""
    if not isinstance(name, str) or not name.strip():
        raise FormError("upload has no file name")
    if len(name) > MAX_FILENAME_CHARS:
        raise FormError("upload file name is too long")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise FormError("upload file name has control characters")
    if "/" in name or "\\" in name or name in (".", "..") or _WINDOWS_DRIVE_RE.match(name):
        raise FormError("upload file name must not contain a path")
    return name


def parse_multipart(body: bytes, content_type: str, *, max_file_bytes: int, max_text_bytes: int = 1024 * 1024) -> tuple:
    """``(fields, files)``: text fields as ``str`` and file parts as :class:`Upload`."""
    boundary = _boundary_of(content_type).encode("latin-1")
    delimiter = b"\r\n--" + boundary
    data = b"\r\n" + body
    segments = data.split(delimiter)
    if len(segments) < 3:
        raise FormError("multipart body is empty")
    # segments[0] is the preamble; the final segment must start with "--" (the closing delimiter)
    if not segments[-1].startswith(b"--"):
        raise FormError("multipart body is not terminated")
    parts = segments[1:-1]
    if len(parts) > MAX_PARTS:
        raise FormError("too many form parts")
    fields = FormData()
    files: dict = {}
    for raw in parts:
        if not raw.startswith(b"\r\n"):
            raise FormError("multipart part is malformed")
        head, sep, content = raw[2:].partition(b"\r\n\r\n")
        if not sep and raw[2:].startswith(b"\r\n"):  # empty header block
            head, content = b"", raw[4:]
        elif not sep:
            raise FormError("multipart part has no body")
        if len(head) > MAX_PART_HEADER_BYTES:
            raise FormError("multipart part headers are too large")
        try:
            headers = BytesHeaderParser().parsebytes(head)
            disposition = headers.get("Content-Disposition", "")
            if not isinstance(disposition, str) or not disposition.lower().startswith("form-data"):
                raise FormError("multipart part is not form-data")
            name = headers.get_param("name", header="content-disposition")
            filename = headers.get_filename()
        except FormError:
            raise
        except Exception:  # noqa: BLE001 - any parser surprise is a bad request
            raise FormError("multipart part is malformed") from None
        if not isinstance(name, str) or not name or len(name) > 64:
            raise FormError("multipart part has no valid name")
        if filename is not None:
            if len(content) > max_file_bytes:
                raise FormError("upload is too large")
            if name in files:
                continue
            if filename == "" and not content:
                continue  # an empty file input
            files[name] = Upload(safe_upload_name(filename), bytes(content))
        else:
            if len(content) > max_text_bytes:
                raise FormError("form field is too large")
            try:
                fields.add(name, content.decode("utf-8"))
            except UnicodeDecodeError:
                raise FormError("form is not valid UTF-8") from None
    return fields, files
