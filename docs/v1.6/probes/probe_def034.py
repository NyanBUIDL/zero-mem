# DEF-034 lifecycle probe (A-I + security J) — portable + assertions (exit != 0 on failure).
import sys, json, tempfile, pathlib, sqlite3

# Portable repo-root resolution (works from any clone/CI checkout).
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.capture.adapter import normalize_event
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.retrieval.db import open_readonly
from tests.unit.test_m3_query import _checkpoint_and_close, _make_env, _write_jsonl

AUDIT = [{"rule": "probe", "fields": []}]
tmp = pathlib.Path(tempfile.mkdtemp())

def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        sys.exit(1)

# A. capture adapter envelope has no top-level ks
env = normalize_event({"text": "hello", "redaction_audit": AUDIT},
                      profile_id="p1", project_id="P", sequence=0,
                      event_type="user_statement", source="hermes_chat")
check("A. envelope has no ks", "knowledge_space_id" not in env)

# B. real canonical append
tmp2 = tmp / "canonical"
store = JsonlCaptureStore(CaptureStoreConfig(tmp2))
receipt = store.append(env)
p = tmp2 / "events-v1.jsonl"
canon = json.loads(p.read_text().splitlines()[0])
check("B. canonical has no ks", "knowledge_space_id" not in canon, receipt.status)

# C. ingest captured -> zm_meta.ks NULL
db = SQLiteStore(SQLiteStoreConfig(path=tmp / "m.sqlite"))
db.ensure_schema()
ingest_file(db, p)
_checkpoint_and_close(db)
conn = sqlite3.connect(str(tmp / "m.sqlite")); conn.row_factory = sqlite3.Row
row = conn.execute("SELECT event_id, knowledge_space_id FROM zm_meta").fetchone()
check("C. zm_meta ks NULL", row["knowledge_space_id"] is None)
conn.close()

# D. hand-crafted canonical WITH ks -> denormalize
jl = tmp / "ks.jsonl"
_write_jsonl(jl, [_make_env("ev-ks", profile_id="p1", project_id="P", knowledge_space_id="quant-theory")])
db2 = SQLiteStore(SQLiteStoreConfig(path=tmp / "m2.sqlite"))
db2.ensure_schema()
ingest_file(db2, jl)
_checkpoint_and_close(db2)
conn2 = sqlite3.connect(str(tmp / "m2.sqlite")); conn2.row_factory = sqlite3.Row
ks2 = {r["event_id"]: r["knowledge_space_id"]
       for r in conn2.execute("SELECT event_id, knowledge_space_id FROM zm_meta")}
check("D. ingest denormalizes ks", ks2.get("ev-ks") == "quant-theory", str(ks2))
conn2.close()

# E. FTS SearchHit carries ks from zm_meta
from src.retrieval.search import search_text
ro = open_readonly(tmp / "m2.sqlite")
res = search_text(ro, "clean content")
ks_e = {h.event_id: h.knowledge_space_id for h in res.results}
check("E. FTS hit carries ks", ks_e.get("ev-ks") == "quant-theory", str(ks_e))
ro.close()

# F. space-grant per-row (ks row authorized, NULL row denied)
from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant
ro = open_readonly(tmp / "m2.sqlite")
svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
grant = AuthorizedReadGrant(grant_id="g1", subject_profile="prof-owner", operation="READ",
                            target_type="knowledge_space", target_id="quant-theory",
                            resource_types=["memory_event"])
res = svc.query_events(AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                                     knowledge_space_ids=["quant-theory"]), grants=[grant])
check("F. space grant returns ks row", [v.event_id for v in res.items] == ["ev-ks"])
svc.close()

# G. rebuild from canonical preserves ks
db3 = SQLiteStore(SQLiteStoreConfig(path=tmp / "m-rebuild.sqlite"))
db3.ensure_schema()
ingest_file(db3, jl)
_checkpoint_and_close(db3)
conn3 = sqlite3.connect(str(tmp / "m-rebuild.sqlite")); conn3.row_factory = sqlite3.Row
v2 = {r["event_id"]: r["knowledge_space_id"] for r in conn3.execute("SELECT event_id, knowledge_space_id FROM zm_meta")}
conn3.close()
check("G. rebuild preserves ks", v2 == ks2, str(v2))

# H. KS via payload -> sanitized_content.extra (not top-level)
env_h = normalize_event({"text": "hi", "knowledge_space_id": "quant-theory", "redaction_audit": AUDIT},
                        profile_id="p1", project_id="P", sequence=1,
                        event_type="user_statement", source="hermes_chat")
extra_h = env_h.get("sanitized_content", {}).get("extra", {})
check("H. payload KS parked in extra", "knowledge_space_id" not in env_h and "knowledge_space_id" in extra_h)

# I. manual top-level ks before append -> canonical keeps
env_i = normalize_event({"text": "hi2", "redaction_audit": AUDIT},
                        profile_id="p1", project_id="P", sequence=2,
                        event_type="user_statement", source="hermes_chat")
env_i["knowledge_space_id"] = "ks-manual"
tmp_i = tmp / "canon_i"
store_i = JsonlCaptureStore(CaptureStoreConfig(tmp_i))
store_i.append(env_i)
line_i = json.loads((tmp_i / "events-v1.jsonl").read_text().splitlines()[0])
check("I. manual top-level ks preserved", line_i.get("knowledge_space_id") == "ks-manual")

# J. security nuance: global read on NULL-profile ignores ks (no widening)
jl_sec = tmp / "sec.jsonl"
_write_jsonl(jl_sec, [
    _make_env("ev-lost-ks", profile_id=None, project_id=None, knowledge_space_id=None),
    _make_env("ev-kept-ks", profile_id=None, project_id=None, knowledge_space_id="secret-ks"),
])
db4 = SQLiteStore(SQLiteStoreConfig(path=tmp / "m4.sqlite"))
db4.ensure_schema()
ingest_file(db4, jl_sec)
_checkpoint_and_close(db4)
ro4 = open_readonly(tmp / "m4.sqlite")
svc4 = AuthorizedReadService(ro4, "stranger", grant_conn=ro4.conn)
r4 = svc4.query_events(AccessRequest(operation="READ", requesting_profile_id="stranger", include_global=True))
ids4 = {v.event_id for v in r4.items}
check("J. global read: both NULL-profile rows visible", "ev-lost-ks" in ids4 and "ev-kept-ks" in ids4, str(sorted(ids4)))
svc4.close()

print("ALL PROBES PASS (A-J)")