# Shared Memory Runtime - design on the Hermes authorization pipeline

Status: DESIGN PROPOSAL (not accepted, no ADR yet). Date: 2026-10-01. Code base: v1.6.1, schema 13.
Goal: one local, zero-LLM memory shared by Claude Code, Codex, Hermes, OpenClaw over MCP; remembers
persona / workflow / skills / dev-history; ingests user files. Reuse `src/access`, `src/corpus`,
`src/integration/m6`; do NOT extend `zero_mem/notes.py` (second truth, outside authorization).

Evidence tags: **[V]** verified by running it this session; **[R]** read from code only; **[U]** not verified.
Paths are repo-relative. Experiments used temp dirs only; scratch scripts are not committed.

## 0. Decisions in one screen

1. Everything (persona, workflow, skill, devlog, fact, user files) is a **corpus source** (`src/corpus`), typed by
   `external_ref="mem://<type>/<id>"` + `custom_meta.memory_type`. M1 events and M4 project memory stay as they are.
2. Identity = **one profile per agent** (`claude-code`, `codex`, `hermes`, `openclaw`); sharing = **one knowledge
   space `ks-shared`** + one READ grant per agent; `project_id` only for devlog. All-NULL scope = operator-curated only.
3. Reads: existing MCP `corpus_search` (+ small additions). Writes: **new, separate** MCP module that calls
   `authorize_write` first, then pre-scans for secrets, then ingests under a cross-process lock.
4. MCP server must **pin the profile server-side** (today the caller asserts it) - P0.
5. Seven P0 items (section 6) block shipping. Two are real defects in existing Hermes code (stale units after an update,
   `authorize_write` scope bypass), not just missing features.

## 1. Ingest one file, retrieve it through the authorized path

| # | Call (module) | Required args / notes |
|---|---|---|
| 1 | `zero_mem.paths.ensure_private_dir(path,label)`, `ensure_empty_memory_stream()` | `zero-mem setup` does this + step 2. Root = env `ZERO_MEM_DATA_ROOT` (absolute) |
| 2 | `SQLiteStore(SQLiteStoreConfig(path: Path)).ensure_schema() -> 13` (`src/storage/sqlite_store.py`) | WAL + `busy_timeout=5000` set at open. Raw connection is `store._conn` (no public accessor) |
| 3 | `CorpusSourceRegistry(root=Path)`, `CorpusBlobStore(root=Path)` | root: explicit > env `ZERO_MEM_CORPUS_ROOT` > None (= unavailable). **No default under data root** |
| 4 | `registry.register_source_with_blob(*, content: bytes, external_ref: str, kind: str, profile_id=None, project_id=None, knowledge_space_id=None, sensitivity="internal", lifecycle_status="observed", custom_meta=None, provenance=None, blob_store=None) -> CorpusSourceRecord` | Canonical write: blob (sha256 path) then fsync'd line in `corpus_sources.jsonl`. `source_id` = hash(`external_ref`,`kind`,scope,`custom_meta`) (`identity.py`); same id + new bytes = new version. `kind` = adapter hint; only `txt`/`text`/`plaintext`/`pdf` resolve today |
| 5 | `project_corpus(conn, registry, blob_store=None) -> CorpusProjectionReport`; then `conn.commit()` | Derived write. Per source: `select_adapter(kind)` -> `adapter.extract` -> `normalize_extraction` -> dedup -> `require_safe` (secret unit rejected) -> `zm_corpus_units` + `zm_corpus_fts`. Re-projects **all** registry sources every call |
| 6 | `GrantAdminService(conn, canonical_writer, verification_lookup=None).create(GrantAdminRequest(action="create", grant_id, subject_profile, operation, target_type, target_id, created_at))` | Trusted control plane; READ needs no `verification_ref`. Writes the canonical `access_grant` event and projects `zm_access_grants` |
| 7 | `open_readonly(path: Path)` (`src/retrieval/db.py`) | Absolute path; `mode=ro`+`query_only`; shared advisory file lock on `<db>.lock` |
| 8 | `AuthorizedReadService(store, requesting_profile_id, grant_conn=None).corpus_unit_search(request: AccessRequest, text: str, *, metadata=None, limit=None, semantic=None, grants=None) -> AuthorizedResult` | `.allowed/.denied/.reason_code/.items: list[CorpusHit]/.error`. **Omit `grant_conn` and persistent grants are silently ignored** [V: 2 vs 4 hits] |

`AccessRequest(operation, requesting_profile_id, target_profile_ids, project_ids, knowledge_space_ids, include_global, isolated_mode, resource_type, resource_id)`.
MCP route to the same facade: `python -m src.integration.m6.mcp_server --store-path <db>`, tool `corpus_search`
(handlers pass `grant_conn=store.conn` and pre-resolved `grants`, `src/integration/m6/handlers.py:82-103,308`).

Executed end to end [V] (output at the bottom; this is the exact file that ran):

```python
import json, os, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp(prefix="zm-demo-"))
os.environ["ZERO_MEM_DATA_ROOT"] = str(tmp / "data")      # derived DB + canonical memory stream
os.environ["ZERO_MEM_CORPUS_ROOT"] = str(tmp / "corpus")  # registry JSONL + blobs (no default exists!)
from zero_mem import paths
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.corpus.registry import CorpusSourceRegistry
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import project_corpus
from src.access import AccessRequest, AuthorizedReadService
from src.access.admin import GrantAdminService, GrantAdminRequest
from src.retrieval.db import open_readonly

paths.ensure_private_dir(paths.derived_root(), "derived dir"); paths.ensure_empty_memory_stream()
store = SQLiteStore(SQLiteStoreConfig(path=paths.derived_db())); store.ensure_schema()
root = Path(os.environ["ZERO_MEM_CORPUS_ROOT"])
registry, blobs = CorpusSourceRegistry(root=root), CorpusBlobStore(root=root)

note = tmp / "persona.txt"
note.write_text("Nyan prefers terse answers.\nAlways run pytest before every commit.\n")
registry.register_source_with_blob(                  # canonical write; NOT authorized, NOT redacted here
    content=note.read_bytes(), external_ref="mem://persona/persona.txt", kind="txt",
    profile_id="claude-code", project_id=None, knowledge_space_id="ks-shared",
    custom_meta={"memory_type": "persona"})
print("projected:", project_corpus(store._conn, registry, blob_store=blobs).as_dict())  # derived write
store._conn.commit()

def append_canonical(ev: dict) -> None:              # grants live in the canonical memory stream
    with paths.memory_stream().open("a", encoding="utf-8") as f: f.write(json.dumps(ev) + "\n")
GrantAdminService(store._conn, append_canonical, None).create(GrantAdminRequest(
    action="create", grant_id="g-codex-ks-shared", subject_profile="codex", operation="READ",
    target_type="knowledge_space", target_id="ks-shared", created_at="2026-10-01T00:00:00Z"))
store.close()

ro = open_readonly(paths.derived_db())               # library path
svc = AuthorizedReadService(ro, "codex", grant_conn=ro.conn)
res = svc.corpus_unit_search(AccessRequest(operation="READ", requesting_profile_id="codex",
        knowledge_space_ids=["ks-shared"], resource_type="corpus_unit"), "pytest commit", limit=5)
print("library:", res.reason_code, [(h.kind, h.normalized_text) for h in res.items]); ro.close()

from src.integration.m6 import mcp_server            # MCP path = what tools/call executes
mcp_server.configure(paths.derived_db())
for who in ("codex", "hermes"):
    r = mcp_server._handle_rpc("tools/call", {"name": "corpus_search", "arguments": {
        "search_text": "pytest commit", "requesting_profile_id": who,
        "knowledge_space_ids": ["ks-shared"], "limit": 5}}, 1)
    env = r["result"]["structuredContent"]
    print("mcp", who, env["status"], [x["normalized_text"] for x in env.get("results", [])])
```
Run: `cd <repo> && PYTHONPATH=. /tmp/venv/bin/python demo.py`. Observed: `projected: {'sources_projected': 1,
'units_projected': 2, 'units_rejected_secret': 0, 'extractions_failed': 0}`; library `ALLOW_EXPLICIT_CROSS_PROFILE_READ`
-> `Always run pytest before every commit.`; `mcp codex SUCCESS [...]`; `mcp hermes EMPTY` (no grant -> no leak).
Also [V]: `kind="pdf"` works with `pypdf` installed in a scratch venv (`tests/fixtures/corpus/sample.pdf` -> 1 unit,
`page=1`; `corrupt.pdf` -> counted in `extractions_failed`); without `pypdf` `PdfAdapter.is_available()` is False.

## 2. Adding a `FormatAdapter`

Contract (`src/corpus/adapters/base.py`): subclass `FormatAdapter(ABC)`; class attrs `format: FormatKind`,
`parser_name: str`; implement `is_available() -> bool`, `supports(kind_hint) -> bool`,
`extract(*, source_ref, content: bytes, kind_hint) -> ExtractionResult`; helper `_fail(source_ref, status, reason, byte_length)`.
- `ExtractionStatus` (`extract.py`): `complete`,`partial` (both success) | `unsupported_format`,`corrupt_source`,
  `parser_unavailable`,`empty_source`,`missing_source`,`permission_denied`,`adapter_failed`. A failure needs `error_reason`.
- `ExtractionUnit(unit_id, kind, text, source_ref, order, page=None, parent_ref=None, meta={})`;
  `kind` in `UnitKind` = text, heading, table, code, figure, metadata, other (unknown -> `other`; DB CHECK, `migrate_10.py:112-130`).
  `unit_id` must be unique per source and stable across runs (it becomes `source_location_id`; unit PK = hash(source_id, unit_id)).
- **Persisted**: `source_location_id`, `normalized_text`, `kind`, `unit_order`, `page`, `parent_ref`. **`meta` is NOT persisted**
  (`derived_store.py:146-151`, no column) -> encode structure in `unit_id`, `parent_ref` (e.g. nearest heading) or the text.
- Adapters receive only bytes + `kind_hint` (= registry `kind`): no filename, no `custom_meta`. The ingest layer must map
  extension/MIME -> `kind` (and today `kind` outside `txt/pdf` is silently unsupported [V]).
- Redaction hook: none per adapter. The only boundary is `require_safe(unit.normalized_text)` in `_insert_unit`
  (`derived_store.py:144`): a hit rejects that unit, increments `units_rejected_secret`. Adapters must not sanitize.
- Optional parsers: lazy import + `is_available()` (pattern: `adapters/pdf.py` `_try_import`). OCR/parse absence must return
  a typed status, never raise.

Steps: (1) new module `src/corpus/adapters/<fmt>.py`; (2) optional `FormatKind` member + alias in `detect()`
(`base.py:17-30`; `select_adapter` only calls `supports()`, so the enum is cosmetic); (3) add to `_default_registry()`
(`adapters/registry.py:42-46`; `register_adapter` dedups by `.format`) and export in `adapters/__init__.py`; (4) tests
copying `tests/unit/test_m10_2_ingestion.py` (determinism, corrupt, empty, secret unit, projection e2e). No change to
normalize/dedup/derived_store/retrieval. Each adapter needs a distinct `.format` value (registry dedup key). [V] A scratch prototype
of md/csv/json-jsonl/docx/xlsx (stdlib only; headings, paragraphs, fenced code, rows, messages), registered at runtime, projected
7 sources (6 + one fake `jpg`, which was counted in `extractions_failed`) -> 16 units, all found through `corpus_unit_search`.
Items marked "design" in the table were not prototyped.

| Format | `kind` hints | Parser | Units | State |
|---|---|---|---|---|
| md | md, markdown | stdlib line scan | heading (`parent_ref` = enclosing heading id), paragraph `text`, fenced `code`; pipe `table` (design) | [V] proto |
| csv/tsv | csv, tsv | `csv` | header `heading` + 1 `table` unit/row `"col=val; ..."`, `parent_ref`=header, row cap | [V] proto |
| chat json/jsonl | json, jsonl, ndjson, chat | `json` | 1 `text` unit/message `"{role}: {content}"`, id `#m{i}`; handles `{role,content}` lines and `{"messages":[...]}` | [V] proto; ChatGPT/Claude export trees [U] |
| docx | docx | `zipfile`+`ElementTree` `word/document.xml` | `pStyle Heading*` -> heading, other `w:p` -> text; `w:tbl` rows -> table (design); cap uncompressed size | [V] hand-built docx, paragraphs only |
| xlsx | xlsx | `zipfile`+`ElementTree` `sharedStrings`, `sheetN.xml` | 1 `table` unit/non-empty row `a \| b`, id `#s{sheet}r{row}`; sheet names need `workbook.xml` | [V] hand-built only; dates/formulas/inlineStr [U] |
| image | png, jpg, jpeg, webp, tiff | optional `PIL`+`pytesseract` (+ `tesseract` binary), lazy | OCR present: `text` units; absent: ONE `metadata` unit (format, WxH via stdlib, "ocr unavailable") + `partial` | design only: no PIL/tesseract here |
| pdf | pdf | `pypdf` (extra `pdf`) | exists | [V] with pypdf |

Image degrade rule: `is_available()` stays True (else `project_corpus` just counts a failure, `derived_store.py:256`); status
`partial` keeps the source searchable by metadata. Because every projection re-extracts all blobs, installing OCR later
upgrades the source automatically - but only once stale-unit cleanup exists (gap 2), else the old metadata unit lingers.
Ingest-layer work (outside adapters): extension/MIME -> `kind`, size cap, path allowlist, chunk long prose: `TxtAdapter` emits
one unit **per line** (`txt.py:63-73`), which hurts recall/ranking for paragraphs - add paragraph chunking (~800 chars, as
`zero_mem/notes.py:chunk_text`) in txt/md. Zip inputs need uncompressed-size and entry caps.

## 3. Profile / project / knowledge space / grants -> "many agents, one memory"

Facts: profile/project/KS ids are **free-form strings, no registry table**; `DENY_UNKNOWN_*` codes exist but are never
emitted (`src/access/contracts.py:73-76`) [R] - "creating" an agent profile = using the string. Sources and units carry
`(profile_id, project_id, knowledge_space_id)`, each nullable, at most one KS (`corpus/contracts.py`). Grants are canonical
`access_grant` JSONL events -> `zm_access_grants`; they survive `zero-mem upgrade` rebuild [V]; no admin CLI exists (DEF-013).

Read behaviour through the MCP path [V] (units: A=`claude-code`/ks-shared, B=`codex`/ks-shared, C=`claude-code` private,
D=`codex` private, E=all-NULL, F=profile NULL/ks-shared; READ grants on ks-shared for claude-code and codex):

| Caller / request | Sees |
|---|---|
| claude-code, implicit | E, C, A (own profile rows in any KS + all-NULL). KS grant NOT applied |
| claude-code, `knowledge_space_ids=[ks-shared]` | E, F, A, B (all profiles' ks-shared rows); **not** private C |
| hermes (no grant), KS=ks-shared | E only (`ALLOW_GLOBAL_READ`, silent, no leak) |
| claude-code, `target_profile_ids=[codex]` | `POLICY_DENIED` |
| any, `isolated_mode=true`, nothing explicit | `POLICY_DENIED`; `include_global=false` hides E |
| project P: own = `target_profile_ids=[self]`+`project_ids=[P]`; others = project READ grant | P rows across profiles; without grant `POLICY_DENIED` |

One request cannot return both private (ks NULL) and shared rows -> add a read composite `memory_recall` (implicit + KS
request, merged, same facade). Quirk [V]: a request for an unknown KS still returns every granted KS (`policy.py:146`,
`grants.py:218`: requested spaces are never validated), i.e. no narrowing.

**Recommended mapping**
- `profile_id` = authoring agent (ownership, private scratch, audit). Pinned server-side per MCP process.
- `knowledge_space_id="ks-shared"` = global memory; 1 READ grant per agent (target_type `knowledge_space`).
  Provision once with a script using `GrantAdminService`. Agent WRITE to ks-shared needs a WRITE grant (section 4).
- `project_id` = repo slug, devlog only; project READ grants when several agents work on one repo.
- All-NULL scope: operator-curated universal docs only. It is readable by any caller including unbound/misconfigured ones, cannot be
  revoked per agent, and agents cannot write it (`authorize_write` -> `DENY_GLOBAL_WRITE`).

| Type | `external_ref` | Scope | Update model |
|---|---|---|---|
| persona | `mem://persona/<facet>` | ks-shared, profile=author | re-ingest same ref = new version (needs gap 2 fix) |
| workflow | `mem://workflow/<name>` | ks-shared | same |
| skill | `mem://skill/<name>` (SKILL.md body) | ks-shared | same |
| devlog | `mem://devlog/<project>/<YYYY-MM-DD>` | project_id, ks-shared optional | one immutable source per day |
| fact | `mem://fact/<sha256[:12]>` | ks-shared | immutable; supersede by a new fact |
| user file | `file://<name>` | caller's choice | by content |

Why corpus and not the alternatives [R]: M1 `EventType` is a closed enum with no persona/workflow/skill
(`src/capture/event_types.py:21-31`); `ZeroMemRuntime`/`open_local_client` (the `zero_mem/core.py` capture path) refuse any
capture root under `$HOME` (`src/integration/zero_mem_runtime.py:97`, `runtime_root.py:42`) and use another database
(`<capture_root>/derived/events.sqlite`, `zero_mem/hermes_integration.py:395`) than `paths.derived_db()`; `_RuntimeWriter` accepts only
user/assistant/tool kinds. M4 is project-bound typed records (charter/requirement/decision/state) - keep it for that.
Least-invasive way to make the type usable (needs an ADR: closed contract `VALID_METADATA_KEYS`, `query_planner.py:58`): JOIN
`zm_corpus_sources` in `retrieve_corpus`, add `external_ref`+`memory_type` to `CorpusHit`, allow `memory_type` as a post-authorization
metadata filter, and forward `metadata=req.filters` in `handle_corpus_search` (`handlers.py:308-310`). Without code: prefix the first
unit with `memory_type: persona` (hack, searchable word only). Agent-authored facts must not look verified: use lifecycle `observed`
(AGENTS.md "unverified claims must not become active"); note lifecycle cannot be promoted later (gap 10).

## 4. MCP server: how it runs, what exists, minimal write additions

Start: `python -m src.integration.m6.mcp_server --store-path <derived.sqlite>` or env `ZM_M6_STORE_PATH`; cwd = repo root or package
installed. [V] Direct `python src/integration/m6/mcp_server.py` from another cwd fails: `from zero_mem.version import ...` runs before the
sys.path fallback (`mcp_server.py:32` vs `:39-42`). stdio JSON-RPC, protocol `2024-11-05`; methods `initialize`, `tools/list`,
`tools/call`, `ping`; `notifications/*` ignored; anything else -32601. Each `tools/call` opens a fresh read-only store
(`handlers._open_facade`) - no long-lived handle. Typical registration (shape only, [U] with real clients; only the stdlib client
`examples/mcp_client_poc.py` and `_handle_rpc` were run): `claude mcp add zero-mem -- <venv>/bin/python -m src.integration.m6.mcp_server --store-path <db>`;
Codex `[mcp_servers.zero-mem] command=..., args=[...]` in `config.toml`; Hermes/OpenClaw: same stdio command.

Tools today (11, **all READ**): `memory_query`, `memory_search`, `memory_get_event`, `memory_get_related` (M3 events);
`project_get_charter`, `project_list_requirements`, `project_list_decisions`, `project_get_state`, `project_list_verifications`,
`project_list_artifacts` (M4); `corpus_search` (units; only `search_text`, `limit` reach the facade, no metadata filter).
Read-only is structural: `Operation` has only READ (`m6/contracts.py:14`), `validate_request` rejects others (`:207`),
`FORBIDDEN_TOOL_NAMES` (`tools.py:17`), tests pin the exact tool list (`tests/unit/test_m6_contracts.py:33`,
`test_m6_hardening.py:75`), and **`authorize_write`/`AuthorizedWriteService`/`GrantAdminService` have zero production
callers** (grep `src zero_mem scripts`) - only tests. So nothing in the product writes through authorization today.

Minimal additions:
- **A. Pin identity (P0).** `--profile-id` / `ZM_M6_PROFILE_ID`; in `_handle_rpc` overwrite `arguments["requesting_profile_id"]`, reject a
  different caller value, drop the property from `tool_schemas()`; optional `--default-ks`. One server process per agent. Today the caller
  asserts the profile (`m6/contracts.py:277`, `handlers.py:72`) [V: any caller passing `codex` reads codex-private rows].
- **B. Write tools in a new module** (e.g. `src/integration/m6w/`), mounted by the same stdio loop; do not edit m6 (its read-only
  invariants and tests stay intact). `memory_add(text, memory_type, name?)` and `memory_ingest(path|content_b64, kind?, memory_type, scope)`.
  Flow per call: (1) closed-schema validation, no identity/scope authority fields, byte caps. (2) Build the WRITE request so it hits exactly
  one dimension [V matrix below]: private = `target_profile_ids=[self]` only -> `ALLOW_LOCAL_WRITE`; shared = `knowledge_space_ids=[ks]` only
  -> needs WRITE grant (`resource_types=["corpus_source"]`, `verification_ref`) else `DENY_CROSS_PROFILE_WRITE`; devlog = `project_ids=[p]` only.
  Never combine profile + KS/project (gap 3). Pass `store._conn` or a `ReadonlyStore`; passing `SQLiteStore` raises `AttributeError`
  (`authorized_write.py:76`) [V]. (3) Only on allow: extract + `normalize` + `scan_extracted_text` **before** `register_source_with_blob`, so rejected
  content never reaches the blob store; reject `sensitivity="secret"` (not enforced downstream, gap 10); for `path` resolve under allowlisted
  roots, refuse symlinks (otherwise an arbitrary-file-read primitive). (4) Under `locked(<corpus_root>/.write.lock, mode="exclusive")`
  (`src/storage/coordination.py`): fresh `CorpusSourceRegistry`, register (`profile_id`=pinned, `custom_meta={"memory_type":...}`,
  `provenance={"channel":"mcp","tool":...}`), project only the new source (needs `project_source()` refactor, gap 11), commit. (5) Return
  `{source_id, source_version_id, units_projected, units_rejected_secret, extraction_status}`; record the decision via `src/access/audit.py` [R].
- **C. `memory_recall`** read composite (section 3) and a default `limit` <= 8 for agents.
- **D. WRITE-grant verification.** `verification_lookup` has no production implementation. `project_memory.reader.get_verification(store, ref)`
  (`reader.py:622`) has the right shape; authoring a *verified* M4 verification record end to end is [U]. For a single-user box an
  operator-approved lookup injected into `AuthorizedWriteService` is code-supported but needs explicit sign-off (AGENTS.md: cross-profile
  writes need review/verification gates).

`authorize_write` matrix [V] (requester `claude-code`, `resource_type=corpus_source`): own profile only -> ALLOW_LOCAL_WRITE | no target ->
DENY_GLOBAL_WRITE | other profile -> DENY_CROSS_PROFILE_WRITE | KS only, no grant -> DENY_CROSS_PROFILE_WRITE | KS only + verified WRITE
grant -> ALLOW_EXPLICIT_CROSS_PROFILE_WRITE | grant for ks-shared but asks ks-other -> DENY | project only: no grant -> DENY_CROSS_PROFILE_WRITE,
with verified WRITE grant -> ALLOW, other project -> DENY | **own profile + any KS (or project), no grant -> ALLOW_LOCAL_WRITE (bypass)**.
`GrantAdminService.create` refuses a WRITE grant whose `verification_ref` does not resolve to a `verified` record (`ValueError`) [V].

## 5. Concurrency: several agents on one data root

Design: derived SQLite is WAL (`sqlite_store.py:133`, busy 5000 ms); MCP readers open per call `mode=ro` + shared advisory lock on `<db>.lock`
(`retrieval/db.py:105`; the lock file is created in the DB dir, so the server needs write permission there). Canonical
registry is an append-only JSONL guarded only by an in-process `RLock` (`registry.py:47`); blob store likewise (`blob_store.py:48`).

Experiments [V] (spawn processes, temp roots; 2 reader processes looping `open_readonly`+`corpus_unit_search`):

| Scenario | Result |
|---|---|
| 4 writers x 30 docs, project at end, 8 s of readers | 0 errors in ~1250 reads; registry 120/120 lines; `integrity_check` ok; `journal_mode=wal` |
| 4 writers x 40, project after every doc | 0 errors; 160/160 sources, units, FTS rows |
| 4 writers x 400, barrier-synced big `project_corpus` | all succeed (0.5-5.7 s, serialized by the WAL write lock; no `database is locked` at this size) |
| 4 processes register identical bytes concurrently | **3/4 crash** `FileNotFoundError` (`blob_store.py:102-105`: all writers share one `<digest>.part` temp name) |
| 4 processes register the same logical source concurrently | **2 registry lines for one version** (dedup is in-memory, `registry.py:165`) |
| in-place `rebuild_from_corpus` with a reader loop (2000 sources, 1.25 s) | of ~307 reads: **154 silently empty, 35 `DOWNSTREAM_ERROR`** |
| same-bytes race wrapped in `locked(<root>/.write.lock, "exclusive")` + fresh registry inside the lock, 6 procs x 3 runs | 6/6 ok every run, exactly 1 registry line |

Conclusions: reads are safe across processes. Writes need a cross-process exclusive lock and a fresh registry snapshot inside it
(long-lived writers hold a stale `_by_id`; `_update_record` at `registry.py:241` would even rewrite the file from one process's
memory - no production caller today). Never run `rebuild_from_corpus` on a live DB; only staged `zero-mem upgrade` (build in a temp DB,
`os.replace`) is reader-safe. Larger-than-4x400 lock waits beyond `busy_timeout` are [U] (extrapolated risk: `project_corpus` holds one
write transaction for the whole pass). One agent process per MCP server + a single writer entry point is the target topology.

## 6. Gaps, defects, risks (prioritized; register each as DEF before fixing, per AGENTS.md)

P0 - blocks "shared memory you can trust"
1. **Self-asserted identity** [V]: `requesting_profile_id` comes from the request (`m6/contracts.py:277`, `handlers.py:72`). Fix: section 4A.
2. **Stale units after a source update** [V]: v2 of a file dropped line 3, yet `line three will be deleted` is still returned
   (`derived_store.py:152` upserts by `unit_id` and never deletes; it also never marks the old version superseded). Breaks persona/workflow edits.
   Fix: per source, `DELETE` units + FTS rows whose `unit_id` is not in the new set (or mark superseded) inside the projection.
3. **`authorize_write` bypass** [V]: profile + any KS/project returns `ALLOW_LOCAL_WRITE` w/o grant (`authorized_write.py:62-73` returns `base`
   when `_primary_target` is ambiguous; contradicts `_requires_grant` at `:114-123`). Needs RED test + maintainer decision.
4. **No wired write/grant path** [R]: no production caller of `authorize_write`/`GrantAdminService`; no grant CLI. Needs provisioning script
   (profiles+grants) and the section 4B module.
5. **Redactor gaps (DEF-049, extended)** [V]: not detected: `sk-ant-...`, `sk-proj-...`, `AKIA...`, `ghp_...`, `github_pat_...`, `xoxb-...`, `AIza...`,
   `sk_live_...`, JWT, `hf_...`, inline `Authorization: Bearer ...`, `postgres://user:pass@host` mid-text, `export GITHUB_TOKEN=...`. Detected: bare line
   `Bearer ...`, `password|api_key|client_secret|access_token|refresh_token = ...`, PEM. Cause: `_BEARER`/`_URL_USER` anchored `^...$`, `_ASSIGN`
   only named keys (`src/redaction/redactor.py:97,99,102`). `zero_mem/notes.py:29` already has a vendor regex to move. **Raw source bytes are
   stored in the blob store before any scan** [V: `password=...` doc -> unit rejected but blob keeps the secret], and there is no blob/registry delete API [V].
6. **`zero-mem upgrade` without `ZERO_MEM_CORPUS_ROOT`** [V]: activates a derived DB with 0 corpus units and still reports `SUCCESS`/`READY`
   (`zero_mem/upgrade.py:182,226`). Add `paths.corpus_root()` default (`data_root()/data/corpus`) used by setup/upgrade/backup/doctor.
7. **Multi-process write races** [V] (section 5): `.part` collision (`blob_store.py:102-105`), duplicate registry lines (`registry.py:165`).
   Fix: unique temp names (`mkstemp`) + cross-process lock + reload inside lock.

P1 - correctness / recall
8. **Hyphen/special-char queries** [V]: `blue-green`, `pre-commit` -> 0 hits (`retrieval.py:183,198` deletes `-` giving `bluegreen`); `C++` becomes prefix `c*`;
   multi-term queries hide it via the OR fallback. Fix: split on special chars into separate quoted tokens. (Vietnamese diacritics fold correctly [V].)
9. **Type/provenance not retrievable** [R]: `meta` unpersisted; `CorpusHit` has no `external_ref`/`custom_meta` (`retrieval.py:92`, `_UNIT_COLUMNS:321`); `corpus_search` hides
   metadata filters. Hits show only a 64-hex `source_id` [V]. See section 3.
10. **No forget / lifecycle transition** [V]: re-registering identical bytes with `lifecycle_status="deleted"` returns the old record (`registry.py:165`); blob store has
    only `put/get/exists`; `sensitivity="secret"` sources are projected and returned although `corpus/contracts.py:26` says withheld [V]; `private` vs `internal` unused.
11. **O(N) projection per add** [V]: 1000 sources, add one -> 0.71 s re-projecting 1001 (`derived_store.py:231-246`); registration itself 0.5 ms/doc. Add `project_source()`.
12. **In-place rebuild not reader-safe** [V] (`derived_store.py:304-330`; section 5).
13. **Silent extraction failures** [V]: `md/docx/csv/json/jpg` register, store blob, yield 0 units; only an aggregate `extractions_failed` (`derived_store.py:252-284`).
    No per-source status; `ExtractionResult.contained_secret` is never set (`extract.py:120`).
14. **Retrieval quality**: per-line units; score = raw term-frequency sum, no IDF/length/recency, ties by profile/project/source id (`retrieval.py:236-262`); default
    limit 100 full-text hits (`query_planner.py` plan) is token-heavy; within-source `duplicate_of` rows still returned [R].

P2 - MCP/transport and structure
15. `isError` tests `"DENIED"` but the status is `POLICY_DENIED` (`mcp_server.py:98`) [V] -> denials look like success. `arguments.tool` overrides the
    called tool (`mcp_wrapper.py:68`) [V] (defeats per-tool client allowlists). `inputSchema` requires a redundant `tool` and sets
    `additionalProperties:false` (`mcp_wrapper.py:47-52`); generic descriptions; the envelope is sent twice (`content` + `structuredContent`).
16. Requested KS is never validated or used to narrow grants [V] (section 3).
17. Topology split `paths.derived_db()` vs runtime `events.sqlite`; default data root is under `$HOME` but `RuntimeConfig` rejects roots under `$HOME` [V]; corpus
    projection is not part of `ProjectionCoordinator`. Shared runtime should use the `paths` layout and bypass `ZeroMemRuntime`.
18. `corpus-store-path` config and the doctor advice (`commands_doctor.py:138`) are vestigial: corpus search reads the main store (`authorized_read.py:1048`,
    `handlers.py:101`); `open_corpus_conn` has no caller [R]. A bad configured path still aborts server start (`m6/runtime.py`) [R].
19. Packaging: `pyproject.toml:36` excludes `scripts*`, so all ingest tooling (quant-lab specific) is not shipped; top-level package is named `src`;
    no console script for the MCP server.
20. `zero_mem/notes.py` + CLI `add/ingest/search` (`zero_mem/cli.py:189-193`): parallel store, own JSONL/SQLite, no authorization. Retire; one-time import of
    `data/notes/notes-v1.jsonl` into corpus sources.
21. Low: derived DB file mode 0644 inside a 0700 dir (`secure_permissions` unused, `sqlite_store.py:264`) [V]; M1 ingest logs grant lines in the memory stream as
    `invalid_record` (harmless, 2 rows) [V].

## 7. Not verified

Real Claude Code / Codex / Hermes / OpenClaw client sessions (schema `required:["tool"]` friction included); OCR path (no PIL/tesseract installed);
real-world docx/xlsx beyond hand-built minimal files; ChatGPT/Claude export formats; a real verified M4 verification record for WRITE grants; lock
timeouts above 4x400 sources; Windows/macOS lock behaviour; JSONL appends of lines > 4 KB under concurrency; the full test suite (only the 59 M10.4/M10.5 tests were run: pass).

## 8. Suggested build order

1. P0 fixes with RED-first tests: identity pin, stale units, `authorize_write` combo, redactor patterns + pre-register scan, `paths.corpus_root()`, lock + `mkstemp`.
2. `zero_mem/memory.py` library: `ingest(path|bytes, kind, memory_type, scope)`, `add(text,...)`, `recall(...)` = the single place for authorize + scan + lock + register + project.
3. Adapters md, csv, json/jsonl, docx, xlsx, image (section 2); paragraph chunking; hyphen fix; `CorpusHit` metadata + ADR.
4. `m6w` write tools + `memory_recall`; reroute CLI `add/ingest/search` to the library; retire `notes.py`.
5. Provisioning script (profiles, `ks-shared`, READ/WRITE grants), runbook, per-client MCP config docs verified with real clients.
