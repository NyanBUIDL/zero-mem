"""QL-2 projection runner — pymupdf-backed adapter + md blob backfill (final).

Tooling-only: no src/ changes. Installs a pymupdf adapter into the M10.2
adapter registry (tooling layer), blob-backs the .md sources, then projects the
canonical corpus into the derived SQLite store for FTS retrieval.
"""
import sys
sys.path.insert(0, ".")
from pathlib import Path
from io import BytesIO
import pymupdf

from src.corpus.adapters.registry import ADAPTER_REGISTRY
from src.corpus.extract import ExtractionResult, ExtractionStatus, ExtractionUnit


class PyMuPdfAdapter:
    parser_name = "pymupdf"

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return kind_hint in ("primary-pdf", "pdf")

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str):
        try:
            doc = pymupdf.open(stream=BytesIO(content), filetype="pdf")
        except Exception:
            return ExtractionResult(
                source_ref=source_ref,
                status=ExtractionStatus.CORRUPT_SOURCE.value,
                units=(), parser_name=self.parser_name, byte_length=len(content))
        if doc.is_encrypted:
            doc.close()
            return ExtractionResult(
                source_ref=source_ref,
                status=ExtractionStatus.UNSUPPORTED.value,
                units=(), parser_name=self.parser_name, byte_length=len(content))
        units = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if not text.strip():
                continue
            units.append(ExtractionUnit(
                unit_id=f"{source_ref[:12]}-p{i}", kind="text", text=text,
                source_ref=source_ref, page=i, order=i))
        doc.close()
        total = sum(len(u.text) for u in units)
        if not units or total < 200 * max(1, len(units)) // 2:
            return ExtractionResult(
                source_ref=source_ref,
                status=ExtractionStatus.EMPTY_SOURCE.value,
                units=tuple(units), parser_name=self.parser_name,
                byte_length=len(content))
        return ExtractionResult(
            source_ref=source_ref,
            status=ExtractionStatus.COMPLETE.value,
            units=tuple(units), parser_name=self.parser_name,
            byte_length=len(content))


ADAPTER_REGISTRY.append(PyMuPdfAdapter())

from src.corpus.registry import CorpusSourceRegistry
from src.corpus.blob_store import CorpusBlobStore
from src.storage.migrations import MIGRATIONS
from src.corpus.derived_store import project_corpus

root = Path("/home/lenovo/Hermes Workspace/zero-mem-dev-data/corpus-quant-lab")
registry = CorpusSourceRegistry(root=root)
blobs = CorpusBlobStore(root=root)

# Blob-back the .md sources (they were registered without blobs originally).
fixed = 0
for rec in registry.all_records():
    if rec.blob_ref is None and rec.kind in ("derived-md", "orphan-md"):
        src_path = Path(rec.provenance.get("source_path", ""))
        if src_path.exists():
            blobs.put(content=src_path.read_bytes(), source_ref=rec.external_ref)
            fixed += 1
print("md sources blob-backed:", fixed)

conn = __import__("sqlite3").connect(str(root / "corpus-derived.sqlite"))
# Apply migrations idempotently (each .up is additive and tolerant of re-run).
for v in sorted(MIGRATIONS):
    try:
        MIGRATIONS[v].up(conn, f"ql v{v}")
    except Exception as e:
        if "already exists" not in str(e):
            raise
conn.commit()

report = project_corpus(conn, registry, blobs)
conn.commit()
print("projected:", {k: v for k, v in report.__dict__.items() if not k.startswith("_")})
