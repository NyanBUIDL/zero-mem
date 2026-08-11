"""Deterministic corpus test fixtures for the M10.2 PDF/TXT adapters.

Generates a minimal *valid* single-page PDF with extractable text, plus a
corrupt PDF. Byte-for-byte deterministic: no timestamps, no randomness.

M10.7 CORRECTION (defect found in prior-verified M10.2)
-------------------------------------------------------
The original version hard-coded hand-computed ``xref`` offsets and a
``startxref`` value that did not match the actual byte layout of the emitted
object stream (declared object offsets 206/284 vs. actual 241/340, and
``startxref 340`` pointing into ``5 0 obj /Type /Font`` instead of the real
``xref`` table at byte 578). A conforming parser follows ``startxref``, lands
on the font object and fails with ``Trailer cannot be read: Unexpected type
'/Font'`` — so ``sample.pdf`` was in fact a CORRUPT file that only ever
presented as ``corrupt_source``.

The defect was invisible while the optional ``pypdf`` parser was absent,
because the two tests that read this fixture through the real parser were
skipped. It is a FIXTURE defect only: the ``PdfAdapter`` classification logic
was correct throughout and needed no change (verified against 601 real PDFs).

The offsets are now COMPUTED from the emitted bytes rather than hand-written,
so the fixture cannot drift out of sync again.
"""
from __future__ import annotations

import os

ROOT = "tests/fixtures/corpus"

#: PDF body objects, in order. Offsets are computed, never hard-coded.
_HEADER = b"%PDF-1.4\n"

_OBJECTS: tuple[bytes, ...] = (
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
    b"4 0 obj\n<< /Length 49 >>\nstream\n"
    b"BT /F1 12 Tf 72 120 Td (Hello Corpus World) Tj ET\n"
    b"endstream\nendobj\n",
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
)


def build_sample_pdf() -> bytes:
    """Assemble a valid PDF, computing every xref offset from real bytes."""
    body = bytearray(_HEADER)
    offsets: list[int] = []
    for obj in _OBJECTS:
        offsets.append(len(body))  # actual byte offset of this object
        body += obj

    xref_offset = len(body)  # actual byte offset of the xref table

    xref = bytearray(b"xref\n")
    xref += f"0 {len(_OBJECTS) + 1}\n".encode("ascii")
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode("ascii")

    trailer = (
        b"trailer\n"
        + f"<< /Size {len(_OBJECTS) + 1} /Root 1 0 R >>\n".encode("ascii")
        + b"startxref\n"
        + f"{xref_offset}\n".encode("ascii")
        + b"%%EOF\n"
    )
    return bytes(body + xref + trailer)


#: A file that is NOT a parseable PDF despite the %PDF magic bytes.
CORRUPT_CONTENT = b"%PDF-1.4\nthis is not a valid pdf <<<<< >>>>\n"


def main() -> None:
    os.makedirs(ROOT, exist_ok=True)
    with open(f"{ROOT}/sample.pdf", "wb") as fh:
        fh.write(build_sample_pdf())
    with open(f"{ROOT}/corrupt.pdf", "wb") as fh:
        fh.write(CORRUPT_CONTENT)


if __name__ == "__main__":
    main()
