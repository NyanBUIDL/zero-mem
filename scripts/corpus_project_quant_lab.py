"""QL-2 projection runner — pymupdf-backed adapter + md blob backfill (final).

Tooling-only: no src/ changes. Installs a pymupdf adapter into the M10.2
adapter registry (tooling layer), blob-backs the .md sources, then projects the
canonical corpus into the derived SQLite store for FTS retrieval.

v1.3.1 (WP-5): all logic wrapped in main(); import has NO side effects.
Root is passed via --root (default: dev-data corpus root). Migration
application checks sqlite_master before calling .up() — idempotent without
string-matching exception text.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_ROOT = Path("/home/lenovo/Hermes Workspace/zero-mem-dev-data/corpus-quant-lab")


class PyMuPdfAdapter:
    parser_name = "pymupdf"

    def __init__(self):
        from _pdf_tooling_guard import require_pymupdf

        self._require_pymupdf = require_pymupdf

    def is_available(self) -> bool:
        try:
            self._require_pymupdf()
            return True
        except SystemExit:
            return False

    def supports(self, kind_hint: str) -> bool:
        return kind_hint in ("primary-pdf", "pdf")

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str):
        from src.corpus.extract import ExtractionResult, ExtractionStatus, ExtractionUnit

        pymupdf = self._require_pymupdf()
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


def install_adapter() -> None:
    """Explicitly register the pymupdf tooling adapter (no import side effect)."""
    from src.corpus.adapters.registry import ADAPTER_REGISTRY

    adapter = PyMuPdfAdapter()
    if not any(getattr(a, "parser_name", None) == adapter.parser_name
               for a in ADAPTER_REGISTRY):
        ADAPTER_REGISTRY.append(adapter)


def _migration_applied(conn: sqlite3.Connection, version: int) -> bool:
    """True when this migration's ledger row already exists (idempotent check
    via sqlite_master, NOT exception-string matching)."""
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='zm_migrations'"
        ).fetchone()
    except sqlite3.Error:
        return False
    if row is None:
        # No ledger yet — migration 1 (which creates the ledger) is pending.
        return False
    applied = conn.execute(
        "SELECT version FROM zm_migrations WHERE version=?", (version,)
    ).fetchone()
    return applied is not None


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations with ledger tracking (mirrors the store's
    `_apply_up` semantics: up() + ledger row, transactional per migration)."""
    from src.storage.migrations import MIGRATIONS

    for v in sorted(MIGRATIONS):
        if _migration_applied(conn, v):
            continue
        conn.execute("BEGIN")
        try:
            MIGRATIONS[v].up(conn, f"ql v{v}")
            conn.execute(
                "INSERT INTO zm_migrations(version, applied_at, note) "
                "VALUES (?, datetime('now'), ?)",
                (v, f"ql v{v}"),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    conn.commit()


def blob_back_md_sources(registry, blobs) -> int:
    """Blob-back the .md sources (they were registered without blobs originally)."""
    fixed = 0
    for rec in registry.all_records():
        if rec.blob_ref is None and rec.kind in ("derived-md", "orphan-md"):
            src_path = Path(rec.provenance.get("source_path", ""))
            if src_path.exists():
                blobs.put(content=src_path.read_bytes(),
                          source_ref=rec.external_ref)
                fixed += 1
    return fixed


def run_projection(root: Path) -> dict:
    from src.corpus.blob_store import CorpusBlobStore
    from src.corpus.derived_store import project_corpus
    from src.corpus.registry import CorpusSourceRegistry

    registry = CorpusSourceRegistry(root=root)
    blobs = CorpusBlobStore(root=root)

    fixed = blob_back_md_sources(registry, blobs)
    print("md sources blob-backed:", fixed)

    conn = sqlite3.connect(str(root / "corpus-derived.sqlite"))
    try:
        apply_migrations(conn)
        report = project_corpus(conn, registry, blobs)
        conn.commit()
    finally:
        conn.close()
    return {k: v for k, v in report.__dict__.items() if not k.startswith("_")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(DEFAULT_ROOT),
                    help="corpus root (dev-data, outside git)")
    args = ap.parse_args()

    install_adapter()
    projected = run_projection(Path(args.root))
    print("projected:", projected)


if __name__ == "__main__":
    main()
