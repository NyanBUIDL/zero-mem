# DEF-034 rebuild probe (G) — portable + assertion (exit != 0 on failure).
import sys, pathlib, sqlite3, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import _checkpoint_and_close, _make_env, _write_jsonl

tmp = pathlib.Path(tempfile.mkdtemp())
jl = tmp / "canon.jsonl"
_write_jsonl(jl, [
    _make_env("ev-ks", profile_id="p1", project_id="P", knowledge_space_id="quant-theory"),
    _make_env("ev-null", profile_id="p1", project_id="P", knowledge_space_id=None),
])

def ingest_once(path):
    db = SQLiteStore(SQLiteStoreConfig(path=path))
    db.ensure_schema()
    ingest_file(db, jl)
    _checkpoint_and_close(db)
    conn = sqlite3.connect(str(path)); conn.row_factory = sqlite3.Row
    out = {r["event_id"]: r["knowledge_space_id"] for r in conn.execute("SELECT event_id, knowledge_space_id FROM zm_meta")}
    conn.close()
    return out

v1 = ingest_once(tmp / "m.sqlite")
v2 = ingest_once(tmp / "m-rebuild.sqlite")
print("v1:", v1)
print("v2:", v2)
assert v1 == v2 and v1.get("ev-ks") == "quant-theory", f"rebuild mismatch {v1} vs {v2}"
print("REBUILD PROBE PASS")