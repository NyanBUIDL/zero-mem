"""Shared fixtures for the T5 Memory tests (not collected: no ``test_`` prefix)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from zero_mem.memory import Memory
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import Provisioner

SHARED = "ks-shared"

# Built at runtime so this file itself never carries a literal credential.
SECRET_TOKEN = "sk-" + "ant-api03-" + "abcdefghijklmnopqrstuvwxyz0123456789"
SECRET_ENV = "password" + "=hunter2hunter2"


class Clock:
    """Deterministic, settable clock for devlog dates."""

    def __init__(self, iso: str = "2026-10-01T09:00:00+00:00") -> None:
        self.now = datetime.fromisoformat(iso)

    def __call__(self) -> datetime:
        return self.now

    def set(self, iso: str) -> None:
        self.now = datetime.fromisoformat(iso).astimezone(timezone.utc)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "zm"
        self.layout = Layout.resolve(self.root)
        self.layout.ensure()
        self.clock = Clock()
        self.prov = Provisioner(self.layout, operator="tester", clock=self.clock)
        self._open: list[Memory] = []

    def open(self, profile: str, **kwargs) -> Memory:
        kwargs.setdefault("clock", self.clock)
        mem = Memory.open(profile, data_root=self.root, **kwargs)
        self._open.append(mem)
        return mem

    def agent(self, profile: str, *, write_shared: bool = False, write_projects=(), read_projects=(), **kw) -> Memory:
        """Register ``profile`` (READ on ks-shared) and optionally approve shared/project writes."""
        self.prov.add_agent(profile)
        if write_shared:
            self.prov.grant_write(profile, space=SHARED, basis="test approval")
        for project in write_projects:
            self.prov.grant_write(profile, project=project, basis="test approval")
        for project in read_projects:
            self.prov.grant_read(profile, project=project)
        return self.open(profile, **kw)

    def close(self) -> None:
        for mem in self._open:
            mem.close()

    # -- inspection ------------------------------------------------------------------------
    def files(self) -> Iterator[tuple[Path, bytes]]:
        for dirpath, _dirs, names in os.walk(self.root):
            for name in names:
                path = Path(dirpath) / name
                if name.endswith((".sqlite3-shm",)):
                    continue
                try:
                    yield path, path.read_bytes()
                except OSError:
                    continue

    def files_containing(self, needle: str) -> list[Path]:
        raw = needle.encode("utf-8")
        return [p for p, data in self.files() if raw in data]

    def registry_lines(self) -> list[dict]:
        path = self.layout.corpus_root / "corpus_sources.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def blob_count(self) -> int:
        return sum(1 for p, _ in self.files() if "blobs" in p.parts and not p.name.endswith(".part"))

    def stream_events(self, event_type: Optional[str] = None) -> list[dict]:
        out = []
        for line in self.layout.memory_stream.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if event_type is None or rec.get("event_type") == event_type:
                    out.append(rec)
        return out

    def units(self) -> list[str]:
        import sqlite3
        conn = sqlite3.connect(self.layout.derived_db)
        try:
            return [r[0] for r in conn.execute("SELECT normalized_text FROM zm_corpus_units ORDER BY unit_id")]
        finally:
            conn.close()
