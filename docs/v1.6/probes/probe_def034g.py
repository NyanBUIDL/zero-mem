# DEF-034 probe G: rebuild/replay preserves ks from canonical?
import sys, tempfile, pathlib, sqlite3
sys.path.insert(0, r"E:\Dev\Project Coding - Zero-mem BUIDL\zero-mem")
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.retrieval.db import open_readonly
from tests.unit.test_m3_query import _checkpoint_and_close, _make_env, _write_jsonl

tmp = pathlib.Path(tempfile.mkdtemp())
jl = tmp / "canon.jsonl"
_write_jsonl(jl, [
    _make_env("ev-ks", profile_id="p1", project_id="P", knowledge_space_id="quant-theory"),
    _make_env("ev-null", profile_id="p1", project_id="P", knowledge_space_id=None),
])

# build derived v1
db = SQLiteStore(SQLiteStoreConfig(path=tmp / "m.sqlite"))
db.ensure_schema()
ingest_file(db, jl)
_checkpoint_and_close(db)
conn = sqlite3.connect(str(tmp / "m.sqlite")); conn.row_factory = sqlite3.Row
v1 = {r["event_id"]: r["knowledge_space_id"] for r in conn.execute("SELECT event_id, knowledge_space_id FROM zm_meta")}
conn.close()
print("derived v1 ks:", v1)

# simulate rebuild: fresh derived DB, re-ingest SAME canonical
db2 = SQLiteStore(SQLiteStoreConfig(path=tmp / "m-rebuild.sqlite"))
db2.ensure_schema()
ingest_file(db2, jl)
_checkpoint_and_close(db2)
conn2 = sqlite3.connect(str(tmp / "m-rebuild.sqlite")); conn2.row_factory = sqlite3.Row
v2 = {r["event_id"]: r["knowledge_space_id"] for r in conn2.execute("SELECT event_id, knowledge_space_id FROM zm_meta")}
conn2.close()
print("derived rebuild ks:", v2)
print("rebuild preserves ks:", v1 == v2)
