# DEF-034 executable probe — knowledge_space_id lifecycle
import sys, json, tempfile, pathlib, sqlite3
sys.path.insert(0, r"E:\Dev\Project Coding - Zero-mem BUIDL\zero-mem")

from src.capture.adapter import normalize_event
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.retrieval.db import open_readonly
from tests.unit.test_m3_query import _checkpoint_and_close, _make_env, _open_store, _write_jsonl

tmp = pathlib.Path(tempfile.mkdtemp())

# ---- A. REAL capture adapter ----
print("=== A. capture adapter envelope ===")
env = normalize_event({"text": "hello"}, profile_id="p1", project_id="P",
                      sequence=0, event_type="user_statement", source="hermes_chat")
print("has knowledge_space_id:", "knowledge_space_id" in env)
print("identity fields:", [k for k in ("profile_id","project_id","session_id","knowledge_space_id") if k in env])

# ---- B. REAL canonical append ----
root = tmp / "canonical"
store = JsonlCaptureStore(CaptureStoreConfig(root))
receipt = store.append(env)
print("\n=== B. canonical append ===")
print("append:", receipt.status, receipt.event_id)
p = root / "events-v1.jsonl"
canon = json.loads(p.read_text().splitlines()[0]) if p.exists() else {}
print("canonical has knowledge_space_id:", "knowledge_space_id" in canon)

# ---- C. ingest real canonical -> zm_meta ----
print("\n=== C. ingest -> zm_meta ===")
db = SQLiteStore(SQLiteStoreConfig(path=tmp / "m.sqlite"))
db.ensure_schema()
ingest_file(db, p)
_checkpoint_and_close(db)
conn = sqlite3.connect(str(tmp / "m.sqlite")); conn.row_factory = sqlite3.Row
row = conn.execute("SELECT event_id, knowledge_space_id, profile_id, project_id FROM zm_meta").fetchone()
print("zm_meta row:", dict(row) if row else None)

# ---- D. hand-crafted canonical WITH ks ----
print("\n=== D. hand-crafted ks envelope -> ingest ===")
jl = tmp / "ks.jsonl"
_write_jsonl(jl, [
    _make_env("ev-ks", profile_id="p1", project_id="P", knowledge_space_id="quant-theory"),
    _make_env("ev-null", profile_id="p1", project_id="P", knowledge_space_id=None),
])
db2 = SQLiteStore(SQLiteStoreConfig(path=tmp / "m2.sqlite"))
db2.ensure_schema()
ingest_file(db2, jl)
_checkpoint_and_close(db2)
conn2 = sqlite3.connect(str(tmp / "m2.sqlite")); conn2.row_factory = sqlite3.Row
rows2 = {r["event_id"]: r["knowledge_space_id"] for r in conn2.execute("SELECT event_id, knowledge_space_id FROM zm_meta")}
print("zm_meta ks:", rows2)

# ---- E. FTS SearchHit ----
print("\n=== E. FTS SearchHit.knowledge_space_id ===")
from src.retrieval.search import search_text
ro = open_readonly(tmp / "m2.sqlite")
res = search_text(ro, "clean content")
for h in res.results:
    print(f"  {h.event_id}: ks={h.knowledge_space_id}")
ro.close()

# ---- F. Authorization: space grant on NULL vs ks rows ----
print("\n=== F. authorization: space grant (per-row ks) ===")
from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant
ro = open_readonly(tmp / "m2.sqlite")
svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
grant = AuthorizedReadGrant(grant_id="g1", subject_profile="prof-owner", operation="READ",
                            target_type="knowledge_space", target_id="quant-theory",
                            resource_types=["memory_event"])
req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                    knowledge_space_ids=["quant-theory"])
res = svc.query_events(req, grants=[grant])
print("space-grant query events:", [v.event_id for v in res.items])
svc.close()
