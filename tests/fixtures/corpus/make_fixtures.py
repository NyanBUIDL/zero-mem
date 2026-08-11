import gzip
import struct
import zlib

# Generate a minimal valid PDF with one page containing extractable text,
# plus a corrupt PDF. Used by M10.2 focused tests. Deterministic.
ROOT = "tests/fixtures/corpus"

# A tiny PDF with a single page and a text stream "Hello Corpus World".
PDF_CONTENT = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 60 >>
stream
BT /F1 12 Tf 72 120 Td (Hello Corpus World) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000206 00000 n 
0000000284 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
340
%%EOF
"""


def main() -> None:
    import os

    os.makedirs(ROOT, exist_ok=True)
    with open(f"{ROOT}/sample.pdf", "wb") as fh:
        fh.write(PDF_CONTENT)
    with open(f"{ROOT}/corrupt.pdf", "wb") as fh:
        fh.write(b"%PDF-1.4\nthis is not a valid pdf <<<<< >>>>\n")


if __name__ == "__main__":
    main()
