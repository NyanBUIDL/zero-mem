"""Standalone local notes store: ingest text/markdown/chat logs, search with FTS5.

Canonical truth is an append-only JSONL file; the SQLite FTS5 index is derived
and rebuildable from it. Zero runtime dependencies, zero LLM calls. Secrets are
rejected at the boundary (fail-closed) via the corpus redaction scanner.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from . import paths

NOTES_STREAM_RELATIVE = Path("data/notes/notes-v1.jsonl")
NOTES_DB_RELATIVE = Path("data/derived/notes.sqlite3")
MAX_CHUNK_CHARS = 800
_TOKEN = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an and are as at be but by did do does for from had has have how i if in is it its me my of on or our "
    "so than that the their them then there these they this to us was we were what when where which who whom "
    "why will with would you your".split()
)
_TURN = re.compile(r"^\s*(user|assistant|human|ai|system|me|bot)\s*:\s*(.*)$", re.I)


class NotesError(RuntimeError):
    """Sanitized notes-store failure."""


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    text: str
    source: str
    score: float


def stream_path() -> Path:
    return paths.data_root() / NOTES_STREAM_RELATIVE


def db_path() -> Path:
    return paths.data_root() / NOTES_DB_RELATIVE


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on blank lines / markdown headings, packing paragraphs up to max_chars."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n|^(?=#{1,6}\s)", text, flags=re.M) if b and b.strip()]
    chunks: list[str] = []
    cur = ""
    for block in blocks:
        while len(block) > max_chars:  # hard-split oversized paragraphs at whitespace
            cut = block.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(block[:cut].strip())
            block = block[cut:].strip()
        if cur and len(cur) + len(block) + 2 > max_chars:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        chunks.append(cur)
    return chunks


def parse_chat(text: str) -> list[str]:
    """Return one chunk per chat turn from JSONL ({role,content}) or 'User: ...' lines."""
    turns: list[str] = []
    stripped = text.lstrip()
    if stripped.startswith("{"):
        ok = True
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                ok = False
                break
            if isinstance(obj, dict):
                content = obj.get("content", obj.get("text"))
                if isinstance(content, list):
                    content = " ".join(str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in content)
                if content:
                    turns.append(f"{obj.get('role', 'user')}: {content}")
        if ok and turns:
            return turns
        turns = []
    cur: list[str] = []
    for line in text.splitlines():
        if _TURN.match(line):
            if cur:
                turns.append("\n".join(cur).strip())
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        turns.append("\n".join(cur).strip())
    return turns or chunk_text(text)


class NotesStore:
    def __init__(self, stream: Path | None = None, db: Path | None = None) -> None:
        self.stream = Path(stream) if stream else stream_path()
        self.db = Path(db) if db else db_path()

    # -- storage ---------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5("
            "text, source UNINDEXED, chunk_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
        )
        return conn

    @staticmethod
    def chunk_id(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _known_ids(self, conn: sqlite3.Connection) -> set[str]:
        return {r[0] for r in conn.execute("SELECT chunk_id FROM notes")}

    def add_chunks(self, chunks: Iterable[str], source: str = "cli") -> dict[str, int]:
        from src.corpus.redact import scan_extracted_text

        added = duplicate = rejected = 0
        conn = self._connect()
        try:
            known = self._known_ids(conn)
            self.stream.parent.mkdir(parents=True, exist_ok=True)
            with self.stream.open("a", encoding="utf-8") as fh:
                for text in chunks:
                    text = text.strip()
                    if not text:
                        continue
                    cid = self.chunk_id(text)
                    if cid in known:
                        duplicate += 1
                        continue
                    if not scan_extracted_text(text).safe:  # central redactor (DEF-049)
                        rejected += 1
                        continue
                    rec = {"chunk_id": cid, "text": text, "source": source, "ts": int(time.time())}
                    fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
                    conn.execute("INSERT INTO notes(text, source, chunk_id) VALUES (?,?,?)", (text, source, cid))
                    known.add(cid)
                    added += 1
            conn.commit()
        finally:
            conn.close()
        return {"added": added, "duplicate": duplicate, "rejected_secret": rejected}

    def add_text(self, text: str, source: str = "cli") -> dict[str, int]:
        return self.add_chunks(chunk_text(text), source)

    def ingest_path(self, path: Path, fmt: str = "auto") -> dict[str, int]:
        files: list[Path] = (
            sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt", ".jsonl", ".log"})
            if path.is_dir() else [path]
        )
        if not files:
            raise NotesError("no ingestable files found")
        totals = {"files": 0, "added": 0, "duplicate": 0, "rejected_secret": 0}
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            kind = fmt if fmt != "auto" else ("chat" if f.suffix.lower() in {".jsonl", ".log"} else "text")
            res = self.add_chunks(parse_chat(text) if kind == "chat" else chunk_text(text), source=str(f.name))
            totals["files"] += 1
            for k in ("added", "duplicate", "rejected_secret"):
                totals[k] += res[k]
        return totals

    def rebuild(self) -> int:
        """Rebuild the derived FTS index from the canonical JSONL."""
        if self.db.exists():
            self.db.unlink()
        conn = self._connect()
        n = 0
        try:
            for rec in self._records():
                conn.execute(
                    "INSERT INTO notes(text, source, chunk_id) VALUES (?,?,?)",
                    (rec["text"], rec.get("source", ""), rec["chunk_id"]),
                )
                n += 1
            conn.commit()
        finally:
            conn.close()
        return n

    def _records(self) -> Iterator[dict]:
        if not self.stream.exists():
            return
        with self.stream.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    # -- retrieval -------------------------------------------------------
    @staticmethod
    def fts_query(query: str) -> str:
        words = _TOKEN.findall(query.lower())
        tokens = [t for t in words if len(t) > 1 and t not in _STOPWORDS] or [t for t in words if len(t) > 1]
        return " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens))

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        match = self.fts_query(query)
        if not match or not self.db.exists():
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT text, source, chunk_id, bm25(notes) FROM notes WHERE notes MATCH ? "
                "ORDER BY bm25(notes) LIMIT ?",
                (match, limit),
            ).fetchall()
        finally:
            conn.close()
        return [Hit(cid, text, src, -score) for text, src, cid, score in rows]

    def count(self) -> int:
        if not self.db.exists():
            return 0
        conn = self._connect()
        try:
            return conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        finally:
            conn.close()
