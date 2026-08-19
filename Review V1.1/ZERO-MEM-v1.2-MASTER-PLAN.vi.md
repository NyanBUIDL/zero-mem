# ZERO-MEM v1.2 — MASTER PLAN BOTTOM-UP

**Trạng thái:** Đề xuất sau đánh giá độc lập v1.1.0
**Mục tiêu:** Đưa Zero-Mem từ các thành phần rời rạc thành một hệ nhớ cục bộ có đường đi production hoàn chỉnh, có thể kiểm chứng và vận hành an toàn.
**Ngữ nghĩa canonical storage đã được refinement và phê duyệt:** từ Zero-Mem v1.2 trở đi, JSONL append-only là nguồn sự thật canonical duy nhất cho memory events/traces; SQLite, FTS, indexes, graph projections, vector indexes và materialized views là derived/materialized state có thể rebuild từ canonical sources. Versioned artifacts chỉ authoritative đối với nội dung artifact riêng; Obsidian/Markdown là human-facing rebuildable projection. Tham chiếu governance: `docs/v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md` và `docs/v1.2.0/decisions/ADR-009-CANONICAL_MEMORY_EVENT_TRUTH_AND_DERIVED_STATE_BOUNDARY.md`. Approval này không cấp quyền implement WP-24.

---

## 1. Quyết định chiến lược

### 1.1 Vấn đề cần giải quyết trước

Đánh giá độc lập đã xác nhận bốn lỗi nền tảng:

1. Hermes có thể đăng ký hook nhưng không có canonical writer, nên capture là no-op.
2. Bốn capability chuẩn (`zero_mem.search`, `get_trace`, `get_task_state`, `get_decisions`) luôn trả về `CAPABILITY_NOT_IMPLEMENTED`.
3. Luồng capture có thể báo `CAPTURED` sau khi append bị từ chối hoặc thất bại.
4. Recovery truy vấn bảng `memories`, trong khi schema thực tế dùng `zm_meta` và các bảng `zm_*`.

Vì vậy, v1.2 không bắt đầu bằng ranking mới, vector database, graph phức tạp hoặc tối ưu hiệu năng. Thứ tự đúng là:

```text
Canonical write correctness
        ↓
Derived-state lifecycle + recovery
        ↓
Authorization-first read service
        ↓
Stable public API + local transport
        ↓
Hermes production composition
        ↓
Context assembly / quality / performance / extensibility
```

### 1.2 Những gì v1.2 không làm

- Không thay JSONL canonical bằng SQLite hoặc vector DB.
- Không để LLM quyết định capture, authorization, ranking, freshness hoặc recovery.
- Không thêm cloud service bắt buộc.
- Không thêm write-back Obsidian trước khi canonical write path, recovery và authorization parity được chứng minh.
- Không xem unit test helper là bằng chứng integration production.

---

## 2. Kiến trúc đích

### 2.1 Ranh giới trách nhiệm

```text
Agent / Hermes / Generic client / Sidecar
                 │
                 ▼
        Public API + Request contracts
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
  Capture service     Authorized read service
       │                   │
       ▼                   ▼
Canonical JSONL      Derived SQLite (read-only queries)
       │                   │
       └──────► Rebuild / watermark / diagnostics ◄──────┘
```

| Thành phần | Sở hữu | Được phép làm | Không được phép làm |
|---|---|---|---|
| `CanonicalWriter` | storage runtime | validate, dedupe, append, fsync, trả durable receipt | đọc/ghi SQLite như nguồn sự thật |
| `ProjectionWorker` | derived runtime | ingest/rebuild SQLite từ JSONL, cập nhật watermark | sửa canonical JSONL |
| `AuthorizedReadService` | access + retrieval | authorize trước candidate discovery, query derived state | đọc raw JSONL tùy ý, bypass grant |
| `PublicClient` | API runtime | lifecycle, typed requests/results, gọi service đã inject | tự suy luận identity hoặc path |
| `LocalSidecar` | transport | framing, size/deadline/concurrency, identity propagation | ranking, grant logic, SQL/raw storage |
| `HermesRuntime` | integration composition | tạo writer/service, đăng ký hook/tool, shutdown | thay đổi Hermes core |

### 2.2 Invariant bắt buộc

1. Canonical JSONL là nguồn sự thật duy nhất cho memory event.
2. Mọi acknowledgement thành công phải đại diện cho append canonical đã durable; derived state có thể lag nhưng phải được biểu diễn rõ.
3. SQLite, FTS, graph, corpus index và projection đều có thể rebuild từ canonical sources.
4. Authorization phải xảy ra trước khi hàng không được phép ảnh hưởng candidate set, điểm số, count hoặc thông báo lỗi.
5. Client không được nâng ceiling policy cho `top_k`, byte, token, deadline hoặc scope.
6. Một capability phải có cùng semantics qua direct API, sidecar và Hermes.
7. Không có LLM/network bắt buộc trong capture, recovery, authorization, retrieval hoặc context assembly.

---

## 3. Lộ trình từ dễ đến khó

## Phase 0 — Release Stabilization (dễ, bắt buộc trước v1.2)

**Mục tiêu:** Loại bỏ các release-blocker xác nhận; có thể phát hành dưới dạng v1.1.1.

### Hạng mục 0.1 — Durable capture receipt

- Thay `EventWriter.append() -> None` bằng kết quả kiểu `AppendReceipt`.
- `AppendReceipt` tối thiểu gồm: `status`, `event_id`, `sequence`, `canonical_durable`, `duplicate_class`, `reason_code`.
- `_CaptureWriter` phải chuyển `AdapterResult` thành receipt hoặc ném `CaptureRejected`; không được im lặng bỏ qua kết quả.
- `ZeroMemClient.capture()` chỉ trả `CAPTURED` khi `canonical_durable=True`; các trạng thái còn lại là typed non-success.

**Thuật toán/công nghệ:** Python dataclass bất biến; JSONL append + `flush` + `fsync`; `fcntl.flock` trên Linux đủ điều kiện.

**Kiểm thử chấp nhận:** mô phỏng lỗi quyền, full disk, lỗi redaction, event trùng; không case nào trả `CAPTURED` khi file canonical không thay đổi.

### Hạng mục 0.2 — Recovery đúng schema

- Thay truy vấn `memories` bằng kiểm tra schema `zm_migrations`, `zm_meta`, checkpoint và watermark.
- Chẩn đoán phân biệt: canonical missing/malformed, derived missing, derived corrupt, schema incompatible, derived stale, ready.
- Test recovery phải dùng database do `zero-mem setup` hoặc rebuild thực sự tạo ra.

**Thuật toán/công nghệ:** SQLite read-only URI (`mode=ro`, không dùng `immutable=1` khi database WAL có thể đang thay đổi); đối chiếu canonical sequence/watermark với ingest checkpoint.

### Hạng mục 0.3 — Bằng chứng artifact

- CI tạo wheel và sdist từ đúng commit release.
- Lưu SHA-256, SBOM tối thiểu, nội dung package và kết quả clean-install Linux.
- Tag chỉ được tạo sau khi artifact hash được ký nhận trong release manifest.

**Exit gate Phase 0:** v1.1.1 hoặc baseline v1.2 có full integration test cho capture receipt, recovery thực, artifact reproducibility.

---

## Phase 1 — Canonical Runtime Foundation (dễ → trung bình)

**Mục tiêu:** Một runtime sở hữu rõ ràng canonical writer, derived lifecycle và shutdown.

### Hạng mục 1.1 — `ZeroMemRuntime`

Tạo composition root duy nhất, nhận `EffectiveConfig` đã validate và khởi tạo:

```text
EffectiveConfig
  → JsonlCaptureStore
  → ProjectionCoordinator
  → AuthorizedReadServiceFactory
  → RuntimeHealth
```

`ZeroMemRuntime` là nơi duy nhất mở writer; adapters không tự tạo writer, không suy luận path và không giữ global mutable state.

### Hạng mục 1.2 — Projection coordinator

Chọn mô hình **write-through asynchronous projection**:

1. append JSONL thành công;
2. enqueue event ID trong queue bounded;
3. worker ingest vào SQLite theo batch nhỏ;
4. ghi watermark/checkpoint trong cùng transaction SQLite;
5. nếu queue đầy hoặc worker lỗi, canonical append vẫn thành công nhưng receipt/status báo `DERIVED_PENDING` hoặc `DERIVED_UNAVAILABLE`.

Không trả về kết quả retrieval “current” nếu derived watermark nhỏ hơn canonical watermark mà request yêu cầu freshness mạnh.

**Công nghệ:** `queue.Queue(maxsize=N)` hoặc async equivalent bounded; thread worker đơn cho mỗi data root; SQLite WAL; transaction theo batch có kích thước/độ trễ bị chặn.

### Hạng mục 1.3 — Multi-process policy

- v1.2 chỉ hỗ trợ Linux local filesystem đã qualified.
- JSONL vẫn dùng process lock.
- SQLite writer chỉ có một projection lease cho mỗi root; reader dùng read-only connection ngắn hạn.
- Lease dùng lock file + PID/start-time, timeout hữu hạn và stale-owner detection.
- Không dùng `while True` polling hay retry vô hạn.

**Exit gate Phase 1:** kill process ở các điểm append/project/rebuild; sau restart canonical truth được giữ, derived state tự nhận diện stale và rebuild được.

---

## Phase 2 — Public Read API Canonical (trung bình)

**Mục tiêu:** Triển khai bốn capability chuẩn với một contract duy nhất.

### Hạng mục 2.1 — Request/response contract

Định nghĩa dataclass hoặc Pydantic v2 model cho:

- `SearchRequest` / `SearchResponse`
- `TraceRequest` / `TraceResponse`
- `TaskStateRequest` / `TaskStateResponse`
- `DecisionsRequest` / `DecisionsResponse`

Envelope chung phải có `status`, `reason_code`, `items`, `provenance`, `freshness`, `partial`, `omitted_count`, `request_id`, `contract_version`.

Trạng thái tối thiểu: `SUCCESS`, `EMPTY`, `POLICY_DENIED`, `CAPABILITY_UNAVAILABLE`, `STALE_DERIVED`, `DEADLINE_EXCEEDED`, `OVERLOADED`, `DOWNSTREAM_ERROR`, `INVALID_REQUEST`.

### Hạng mục 2.2 — Mapping từ capability đến service nội bộ

| Capability chuẩn | Primitive nội bộ được phép dùng |
|---|---|
| `zero_mem.search` | authorized FTS/corpus retrieval + ranking |
| `zero_mem.get_trace` | authorized event/provenance/relations lookup |
| `zero_mem.get_task_state` | authorized project state + linked resources |
| `zero_mem.get_decisions` | authorized decisions + lifecycle/conflict |

Internal `memory_*` và `project_*` có thể còn tồn tại như compatibility adapters, nhưng không được là public contract mới.

### Hạng mục 2.3 — Authorization-first query planning

Pipeline bắt buộc:

```text
identity → effective scope/grants → authorized SQL predicates
→ candidate query → deterministic ranking → freshness gate → response budget
```

Không truy vấn toàn bộ candidate rồi lọc authorization sau. Với scope union, tạo predicates có tham số từ scope đã được cấp; không ghép SQL bằng chuỗi input.

**Thuật toán:** FTS5 BM25 chỉ dùng trong tập đã authorized; tie-break ổn định bằng `(score, created_at, event_id)` với hướng sort được quy định; keyset pagination có fingerprint bao gồm scope, query và policy version.

**Exit gate Phase 2:** test parity direct API, test hidden-ID non-probing, cross-profile/knowledge-space leakage, stale derived, deadline và pagination.

---

## Phase 3 — Local Sidecar / MCP (trung bình)

**Mục tiêu:** Sidecar thực sự là transport của canonical API, không phải dispatcher stub.

### Hạng mục 3.1 — Transport lựa chọn

Ưu tiên **stdio MCP** cho agent desktop/CLI vì không cần listener, đơn giản về quyền truy cập và lifecycle. Chỉ thêm Unix domain socket nếu có nhu cầu nhiều local process.

- Không dùng HTTP listener mặc định.
- Nếu Unix socket: socket nằm trong private runtime dir, kiểm tra ownership/mode `0600`, chống endpoint replacement/symlink.
- Tất cả request phải có identity đã xác thực bởi host hoặc explicit local credential; không tin `identity` tự do từ payload.

### Hạng mục 3.2 — Boundedness

- `max_request_bytes`, `max_response_bytes`, `max_concurrency`, `queue_capacity`, deadline do server policy sở hữu.
- Semaphore bounded; timeout hữu hạn; cancel propagation.
- Không tạo task/thread không giới hạn.

### Hạng mục 3.3 — Parity

Sidecar chỉ serialize/deserialize và gọi `PublicClient`; không có đường SQL, authorization hay ranking riêng.

**Exit gate Phase 3:** cùng fixture cho direct client và sidecar cho byte-stable normalized responses; fuzz malformed/oversized input; test sidecar unavailable không làm Hermes chết.

---

## Phase 4 — Hermes Production Composition (trung bình → khó)

**Mục tiêu:** Biến descriptor thành tích hợp chạy thật, có ownership lifecycle rõ ràng.

### Hạng mục 4.1 — Bootstrap

Hermes plugin entrypoint phải:

1. đọc descriptor Zero-Mem đã validate;
2. tạo `ZeroMemRuntime` với data root explicit;
3. đăng ký capture hooks bằng runtime writer;
4. đăng ký bốn read capability bằng runtime read service hoặc sidecar client;
5. đăng ký `pre_llm_call` injection;
6. shutdown theo thứ tự: stop accepts → flush projection bounded → close reader/writer → release lease.

`zero-mem integrate hermes` chỉ trả `CONFIGURED` khi có entrypoint được Hermes load. `READY` yêu cầu health check runtime thực, không chỉ tồn tại descriptor.

### Hạng mục 4.2 — Capture hooks

- Hook callback không được swallow `CaptureReceipt`; ghi metric theo `captured`, `duplicate`, `rejected`, `failed`, `derived_pending`.
- Capture failure phải không làm Hermes fail; nhưng diagnostics phải quan sát được.
- Payload được deep-copy, redact và validate trước canonical writer.

### Hạng mục 4.3 — Pre-LLM injection

- Router xác định memory-needed bằng policy deterministic.
- `EXTERNAL_CURRENT` không được thay bằng memory cũ.
- Context chỉ là data envelope, có source/provenance/freshness; không ghi lại vào transcript canonical như model output.

**Exit gate Phase 4:** E2E với PluginContext thực hoặc compatibility harness sát Hermes: hook → JSONL → projection → retrieval → context injection → restart → retrieval lại.

---

## Phase 5 — Context Quality và Retrieval Evolution (khó)

**Mục tiêu:** Cải thiện usefulness mà không phá authorization, determinism hay provenance.

### Hạng mục 5.1 — Baseline lexical retrieval

- FTS5 với query normalization rõ ràng.
- Metadata filters được push xuống SQL: profile, project, knowledge space, lifecycle, verification, retention, time range.
- Deleted/superseded content bị loại trước ranking.

### Hạng mục 5.2 — Deterministic ranking

Khởi đầu với score có thể giải thích được:

```text
final_score =
  lexical_score
  + provenance_bonus
  + verification_bonus
  + bounded_recency_score
  - conflict_penalty
  - superseded_penalty
```

Mọi weight phải được versioned trong config governed; client không được override. Lưu `ranking_version` và các score components trong result diagnostics an toàn.

### Hạng mục 5.3 — Hybrid retrieval chỉ sau benchmark

Dense/vector retrieval là tùy chọn, không phải prerequisite:

- Embedding local có version/model hash rõ ràng.
- Candidate dense cũng phải trong authorized scope trước similarity/ranking.
- Fusion dùng Reciprocal Rank Fusion hoặc normalized weighted fusion, kèm tie-break deterministic.
- Khi index vector stale/missing, trả typed status hoặc lexical fallback được ghi rõ; không bịa freshness.

**Công nghệ đề xuất:** SQLite FTS5 vẫn là baseline; vector extension hoặc hnswlib chỉ được thêm sau benchmark corpus >= 10k/100k/1M units và threat model dependency.

### Hạng mục 5.4 — Context budget

- Budget theo token estimator deterministic, không gọi LLM.
- First-fit theo ranking sau đó packing greedily trong `max_evidence_tokens`.
- Luôn ưu tiên primary evidence có provenance; supporting evidence bị cắt có `omitted_count`.
- Không cắt giữa UTF-8/code point; không bỏ provenance khi rút gọn.

**Exit gate Phase 5:** benchmark precision/recall có corpus gán nhãn; không tuyên bố benchmark score khi chưa đo.

---

## Phase 6 — Profiles, Knowledge Spaces và Obsidian (khó)

**Mục tiêu:** Mở rộng dữ liệu mà không tạo thêm source of truth.

### Hạng mục 6.1 — Scope model

`profile_id`, `project_id`, `knowledge_space_id` là identity/scope explicit trong canonical event và authorized predicate. Chỉ có một policy evaluator cho direct API, sidecar và Hermes.

### Hạng mục 6.2 — Obsidian projection

Giữ mô hình one-way, deterministic, conflict-preserving:

```text
canonical JSONL → derived views → markdown projection
```

Không write-back tự động. Nếu cần bidirectional sync, dùng **Candidate Review Queue**: Obsidian edit → proposed canonical event → validation/policy/human approval → canonical append. Không bao giờ coi file Markdown là canonical truth trực tiếp.

**Exit gate Phase 6:** cross-profile leakage tests, symlink/path traversal tests, human edit conflict preservation và rebuild projection byte-stable.

---

## Phase 7 — Reliability, Performance và Release Discipline (khó, chạy xuyên suốt)

### 7.1 Failure matrix bắt buộc

| Sự cố | Hành vi yêu cầu |
|---|---|
| Kill khi append | final partial line bị phát hiện; không tự sửa dữ liệu |
| Kill sau append trước projection | canonical durable; derived `STALE_DERIVED`; rebuild được |
| SQLite corrupt/missing | retrieval fail closed; rebuild từ canonical |
| Disk full/quyền lỗi | không trả capture success; canonical cũ không bị đổi |
| Sidecar timeout/overload | typed error; Hermes vẫn hoạt động không memory |
| Nhiều writer | lock/lease hữu hạn; không duplicate/lost sequence |
| Backup/restore interrupted | staging + atomic promotion hoặc rollback rõ ràng |

### 7.2 Performance plan

Đo trên Linux qualified, không dùng claim cảm tính:

- Corpus: 1k, 10k, 100k, 1M event/unit.
- Đo p50/p95 capture, projection lag, search latency, context assembly, rebuild, startup, backup/restore.
- Kiểm tra `EXPLAIN QUERY PLAN` cho các query hot; index theo predicate/sort thực tế.
- Áp dụng keyset pagination thay `OFFSET` ở dataset lớn.
- Bounded caches có TTL/size; không cache authorization quyết định theo request khi grant có thể thay đổi.

### 7.3 Release gates

1. Linux CPython 3.11 và 3.12 clean test pass.
2. Windows/macOS được đánh dấu rõ: supported, best-effort hoặc unsupported; metadata và installer nhất quán.
3. Full E2E cho direct API, sidecar, Hermes.
4. Chaos/failure matrix pass.
5. Artifact wheel/sdist được cài trong fresh venv, hash và contents được kiểm tra.
6. SBOM/license/dependency scan; không chứa test, path developer, credential hoặc temporary files.
7. Không có finding CRITICAL/HIGH chưa được chấp nhận rõ ràng.

---

## 4. Cấu trúc work package đề xuất

| WP | Tên | Phụ thuộc | Độ khó |
|---|---|---|---|
| WP-24 | v1.1.1 correctness backport | — | Dễ |
| WP-25 | Runtime ownership + capture receipt | WP-24 | Trung bình |
| WP-26 | Projection coordinator + freshness watermark | WP-25 | Trung bình |
| WP-27 | Recovery/rebuild/backup conformance | WP-25, WP-26 | Trung bình |
| WP-28 | Canonical public API contracts | WP-25, WP-26 | Trung bình |
| WP-29 | Authorization-first read parity | WP-28 | Khó |
| WP-30 | MCP/sidecar production transport | WP-28, WP-29 | Trung bình |
| WP-31 | Hermes lifecycle composition | WP-25, WP-29, WP-30 | Khó |
| WP-32 | Context assembly + deterministic ranking | WP-29, WP-31 | Khó |
| WP-33 | Retrieval benchmarks + optional hybrid index | WP-32 | Khó |
| WP-34 | Profiles/knowledge spaces/Obsidian review queue | WP-29, WP-32 | Khó |
| WP-35 | Release qualification and artifact provenance | Tất cả | Trung bình |

---

## 5. Definition of Done cho v1.2.0

v1.2.0 chỉ được coi là sẵn sàng khi tất cả điều sau đúng:

- Capture Hermes ghi canonical JSONL thật, có durable receipt và restart proof.
- Bốn capability chuẩn hoạt động qua direct API, sidecar và Hermes với contract tương đương.
- Authorization trước candidate discovery được chứng minh bằng test leakage âm tính.
- Derived state lag/corrupt/missing không thể giả là current; recovery và rebuild hoạt động trên schema thật.
- Context có provenance, freshness, budget và deterministic ordering.
- Linux support matrix có kết quả tái lập; nền tảng khác có trạng thái minh bạch.
- Wheel/sdist phát hành khớp hash, clean-install và không chứa nội dung ngoài ý muốn.

## 6. Thứ tự triển khai khuyến nghị

```text
Tuần 1–2: WP-24
Tuần 3–5: WP-25 + WP-26
Tuần 6:   WP-27
Tuần 7–9: WP-28 + WP-29
Tuần 10:  WP-30
Tuần 11–13: WP-31
Tuần 14–16: WP-32
Tuần 17+: WP-33 / WP-34 song song khi core đã ổn định
Cuối: WP-35
```

Các mốc tuần là ước lượng sequencing, không phải cam kết lịch. Không bắt đầu WP-32 trở lên nếu acceptance gate của WP-29 chưa đạt.
