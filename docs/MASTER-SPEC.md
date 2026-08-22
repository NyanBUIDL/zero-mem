> **Nguồn:** Bản chuyển đổi (Markdown) từ `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
> DOCX là bản authoritative duy nhất. File này là bản đọc/projection để tra cứu và diff nhanh;
> khi mâu thuẫn, luôn ưu tiên DOCX. Tự sinh 2026-08-22; không chỉnh tay nội dung.

TÀI LIỆU THỐNG NHẤT
EXTERNAL ZERO-MEM

Memory Substrate cho toàn bộ Hermes Agent

Kiến trúc nền tảng - Obsidian Knowledge Workspace - Profile - Knowledge Space - Sidecar - MCP - Lộ trình triển khai

> Định vị tài liệu: Đây là tài liệu kiến trúc và triển khai duy nhất cho hệ thống External Zero-Mem của Hermes. Conversation, tool, task, decision và research đều thuộc memory substrate; Obsidian là lớp projection và PDF chỉ là một nguồn dữ liệu.

Bản thống nhất chính thức - Tháng 08/2026

Điều kiện - Kiến trúc - Cách xây dựng - Lộ trình triển khai

# Thông tin tài liệu

| Tên tài liệu | External Zero-Mem Memory Substrate cho toàn bộ Hermes Agent |
| --- | --- |
| Trạng thái | Tài liệu thống nhất chính thức; dùng thay cho mọi bản nháp trước |
| Mục đích | Xác định điều kiện, hướng xây dựng, kiến trúc, phương pháp, schema, lộ trình và tiêu chí nghiệm thu |
| Phạm vi | Conversation, session, tool, task, decision, artifact, preference, research và knowledge systems |
| Kiến trúc lưu trữ | SQLite/JSONL + artifact store là canonical; Obsidian là Knowledge Workspace và curated projection. |
| Nguồn tham chiếu | Zero-Mem paper; yêu cầu về External Zero-Mem, profile và knowledge system do người dùng cung cấp |
| Định dạng | DOCX tương thích Microsoft Word, LibreOffice và Google Docs |

# Mục lục

1. Tóm tắt điều hành

2. Bối cảnh và phạm vi đúng

3. Mục tiêu, ngoài phạm vi và nguyên tắc

4. Điều kiện cần xây dựng

5. Kiến trúc mục tiêu

6. Mô hình trace và provenance

7. Vòng đời memory, trạng thái và xung đột

8. Profile và hệ thống kiến thức

9. Kiến trúc lưu trữ

10. Capture và ingestion pipeline

11. Retrieval, routing và context injection

12. Obsidian Knowledge Workspace và lớp projection

13. Tích hợp Hermes qua Sidecar và MCP

14. Bảo mật, quyền riêng tư và quản trị

15. Chiến lược tiết kiệm token

16. Cách xây dựng chi tiết

17. Kiểm thử và tiêu chí nghiệm thu

18. Lộ trình triển khai

19. Vận hành sau triển khai

20. Rủi ro và biện pháp xử lý

21. Cấu hình mặc định và bước bắt đầu

Phụ lục A-G

# 1. Tóm tắt điều hành

Hệ thống cần xây dựng không phải chỉ là một kho truy xuất 600 PDF. Mục tiêu đúng là tạo một External Zero-Mem Memory Substrate cho toàn bộ Hermes Agent. Lớp này ghi nhận, tổ chức và truy xuất các trace gốc từ hội thoại, session, tool, project, task, quyết định, artifact, preference và research. Hermes chỉ nhận một tập bằng chứng nhỏ, có provenance và trạng thái rõ ràng trước khi suy luận hoặc hành động.

> Kiến trúc cốt lõi: Hermes điều phối và hành động; Zero-Mem sidecar lưu trace, lập index, truy xuất và hiệu chỉnh evidence; LLM chỉ đọc evidence cần thiết để suy luận và tạo đầu ra cuối.

- SQLite/JSONL là canonical trace store; raw artifact được lưu riêng và ưu tiên append-only.

- Obsidian là lớp hiển thị, audit và chỉnh sửa curated memory; không lưu mọi raw tool output.

- Mỗi profile có behavior, tool policy, memory priority, knowledge priority và privacy limits riêng.

- Default có thể truy cập toàn cục nhưng retrieval luôn profile-first và giới hạn evidence budget.

- Không gọi LLM cho capture, indexing, routing, retrieval, dedup, graph traversal và deterministic calibration.

- Chỉ verified state có trọng số cao khi tiếp tục task; assistant self-report không tự trở thành fact.

Tài liệu này hợp nhất Obsidian Knowledge Workspace, profile, knowledge space, provenance, hybrid retrieval, MCP và quản trị trace trong một kiến trúc duy nhất. Obsidian là không gian làm việc tri thức và bảng điều khiển dành cho người dùng; SQLite/JSONL vẫn là nguồn trace gốc. Tất cả module phải được xây theo lộ trình sidecar-first để giữ tính kiểm chứng và giảm token.

# 2. Bối cảnh và phạm vi đúng

## 2.1. Vấn đề thực tế

- Hermes làm việc qua nhiều session, tool và project; context hiện tại không đủ để giữ toàn bộ lịch sử.

- Việc nhồi lại conversation, tool output, skill và tài liệu cũ làm chi phí token tăng nhanh.

- Tóm tắt memory bằng LLM có thể bỏ sót chi tiết, trộn chủ thể hoặc làm mờ trạng thái thời gian.

- Flat RAG có thể lấy đúng nội dung nhưng sai project, sai phiên bản hoặc sai trạng thái hiện tại.

- Một câu trả lời của assistant có thể chỉ là self-report; hệ thống cần tool verification trước khi coi là trạng thái thật.

## 2.2. Phạm vi dữ liệu

| Nhóm trace | Ví dụ | Mục đích truy xuất |
| --- | --- | --- |
| Conversation | User message, assistant response, timestamp, session | Khôi phục bối cảnh và yêu cầu trước |
| Tool observation | Command, API response, exit code, file diff, test result | Xác minh trạng thái thực tế |
| Task state | Requested task, step, failure, unresolved item, completion evidence | Tiếp tục công việc qua session |
| Decision | Chosen option, rejected alternatives, constraint, rationale | Giữ tính nhất quán kiến trúc |
| User memory | Preference, stable environment, working style | Cá nhân hóa có kiểm soát |
| Project artifact | File, config, skill, prompt, report, code, cron | Liên kết hành động với đầu ra |
| Research source | PDF, web page, citation, extracted evidence | Trả lời có provenance |
| Knowledge system | Obsidian notes, glossary, learning path, domain corpus | Hỗ trợ profile chuyên biệt |

## 2.3. Ranh giới hệ thống

> Sơ đồ ranh giới trách nhiệm

```text
Hermes Agent
  -> chat / tools / jobs / skills
  -> emits events

Zero-Mem Sidecar
  -> capture / redact / classify / index / retrieve
  -> returns bounded evidence

Final LLM
  -> reasoning / decision / answer / action plan

Obsidian
  -> curated human-readable projection and audit UI
```

# 3. Mục tiêu, ngoài phạm vi và nguyên tắc

## 3.1. Mục tiêu chức năng

1. Ghi nhận trace của Hermes theo schema thống nhất và có provenance.

2. Truy xuất đúng session, project, entity, thời điểm và verified state.

3. Cho phép nhiều profile có knowledge system riêng nhưng vẫn hỗ trợ global access và explicit combination.

4. Giảm context token bằng retrieval cục bộ và evidence budget có giới hạn.

5. Cho phép người dùng audit, sửa và curate thông tin quan trọng qua Obsidian.

6. Bảo vệ dữ liệu nhạy cảm bằng redaction, access scope, retention và delete workflow.

7. Đo chất lượng retrieval, citation, latency, token và khả năng tiếp tục task.

## 3.2. Ngoài phạm vi giai đoạn đầu

- Không sửa sâu Hermes core ngay từ ngày đầu; triển khai sidecar trước.

- Không tự động inject memory vào mọi prompt trong giai đoạn observation-only.

- Không dùng LLM để tóm tắt mọi turn hoặc mọi PDF khi ingest.

- Không coi Obsidian Graph View là graph retrieval engine.

- Không tự động nâng inference hoặc assistant claim thành permanent fact.

- Không triển khai multi-tenant enterprise, graph database lớn hoặc distributed infrastructure trước MVP.

## 3.3. Nguyên tắc bắt buộc

| Nguyên tắc | Yêu cầu triển khai |
| --- | --- |
| Trace-first | Giữ raw trace và provenance; mọi view chỉ là index hoặc projection. |
| Deterministic before generative | Dùng metadata, FTS, embeddings local, rules và graph traversal trước LLM. |
| Verified state over self-report | Tool observation và kiểm thử có trọng số cao hơn assistant claim. |
| Profile as policy | Profile điều khiển behavior, memory scope, knowledge priority, tool và privacy. |
| Global access, bounded context | Có thể tìm toàn hệ thống nhưng chỉ gửi evidence tối thiểu. |
| Conflict visibility | Không tự chọn âm thầm khi nguồn hoặc trạng thái mâu thuẫn. |
| Privacy by design | Redaction trước persist, retention và delete là thành phần nền tảng. |
| Obsidian as workspace + projection | Profile, project, knowledge space và curated memory hiển thị trong một Vault; raw event store tối ưu riêng. |

# 4. Điều kiện cần xây dựng

## 4.1. Điều kiện về quyết định kiến trúc

- Chấp nhận sidecar là bước đầu, không thay đổi Hermes core ngay.

- Chốt SQLite/JSONL là canonical raw trace; Obsidian là Knowledge Workspace và curated projection.

- Chốt taxonomy trace, lifecycle state, sensitivity và retention trước khi ingest thật.

- Chốt default profile, profile-first global access và explicit/isolated overrides.

- Chốt rằng final answer là bước LLM chính; memory operation LLM calls có mục tiêu bằng 0.

## 4.2. Điều kiện về hạ tầng

- Python 3.11+ trong virtual environment riêng.

- SQLite có FTS5; file system có snapshot/backup; Git chỉ dùng cho code và curated text.

- Embedding model local và vector index local; MVP có thể dùng FAISS hoặc Qdrant.

- Đủ dung lượng cho raw trace, artifact, extracted text, embeddings và index version.

- MCP hoặc local HTTP/Unix socket để Hermes gọi retrieval service.

- Cơ chế log, metrics và health check tách khỏi trace người dùng.

## 4.3. Điều kiện về dữ liệu

- Mọi event có event_id, timestamp, session_id, profile_id, project_id khi có.

- Raw content và derived metadata tách biệt.

- Tool result ghi exit code, success/failure, command/tool name và artifact references.

- PDF/document chunk giữ page/section/offset/checksum.

- Dữ liệu nhạy cảm phải được nhận diện và redacted trước khi persist.

- Một trace có thể thuộc nhiều knowledge space nhưng chỉ có một source-of-record.

## 4.4. Điều kiện về nhân sự và vận hành

- Một người chịu trách nhiệm schema và migration.

- Một bộ benchmark nội bộ có gold evidence trước khi tối ưu retrieval.

- Runbook backup, restore, rebuild index và delete request.

- Quy trình review để nâng candidate memory thành confirmed/active.

# 5. Kiến trúc mục tiêu

> Kiến trúc mục tiêu

```text
[Hermes Agent]
  chat | tools | jobs | skills
          |
          | event stream
          v
[Zero-Mem Capture Sidecar]
  redact | classify | provenance | append
          |
          +-------------------------+
          |                         |
          v                         v
[Raw Trace Store]            [Artifact Store]
 SQLite + JSONL               files + PDF + logs
          |                         |
          +-------------+-----------+
                        v
              [Deterministic Metadata]
       session | project | profile | state | hash
                        |
        +---------------+---------------+
        |               |               |
        v               v               v
 [Temporal Index] [Relational Index] [Search Index]
 sessions/state    entity/links       FTS/vector
        +---------------+---------------+
                        v
              [Evidence Router]
 scope | rank | closure | conflict | budget
                        |
                        v
              [Bounded Evidence Set]
 provenance | verification | status | source
                        |
                        v
                  [Hermes Final LLM]

[Obsidian Vault] = curated projection + audit + human editing
```

## 5.1. Thành phần và trách nhiệm

| Thành phần | Trách nhiệm | Không nên làm |
| --- | --- | --- |
| Hermes Agent | Resolve profile, gọi tool, suy luận, hành động, trả lời | Không lưu corpus lớn trong native memory |
| Capture Sidecar | Nhận event, redact, chuẩn hóa, append trace | Không tự suy diễn fact |
| Raw Trace Store | Nguồn gốc bất biến/append-only | Không dùng làm prompt trực tiếp |
| Index Layer | FTS, embeddings, temporal, relational | Không thay thế provenance |
| Evidence Router | Scope, rank, closure, conflict, budget | Không gọi LLM ở MVP |
| Obsidian Knowledge Workspace | Quản lý profile, knowledge space, project, quyết định, task state; curate, audit và duyệt memory | Không lưu mọi stdout/stderr thô hoặc ghi đè canonical trace |
| Final LLM | Đọc evidence, suy luận, quyết định, trả lời | Không tự sửa memory state âm thầm |

## 5.2. Luồng dữ liệu chính

```text
Capture flow:
Hermes event -> redaction -> schema validation -> append raw trace
             -> metadata extraction -> index update -> optional projection

Query flow:
User query -> profile resolver -> memory need router -> scope filters
           -> hybrid retrieval -> closure -> calibration -> evidence budget
           -> Hermes final reasoning/action

Write-back flow:
Hermes proposal -> write policy -> generated area -> human/verification gate
                -> curated memory -> index refresh
```

# 6. Mô hình trace và provenance

## 6.1. Taxonomy trace

| Type | Nguồn | Độ tin cậy mặc định | Ví dụ |
| --- | --- | --- | --- |
| user_statement | Người dùng | Cao đối với ý định/preference; không tự xác minh external fact | "Từ nay ưu tiên profile Quant" |
| assistant_claim | Assistant | Thấp đến trung bình | "Index đã hoàn thành" |
| tool_observation | Tool/terminal/API | Cao nếu có exit code và output nguyên gốc | Test passed, file exists |
| system_event | Runtime | Cao | Session started, task scheduled |
| external_source | PDF/web/file | Phụ thuộc source quality | Trang 3 của paper |
| inference | Agent/rule | Trung bình hoặc thấp | Suy luận từ nhiều trace |
| decision | Người dùng hoặc workflow đã xác nhận | Cao | Chọn SQLite làm canonical store |
| verified_state | Tool + rule/approval | Rất cao | Deployment healthy sau health check |
| derived_summary | Rule hoặc LLM | Không phải source-of-record | Tóm tắt session |

## 6.2. Provenance envelope bắt buộc

```text
trace_id: uuid
trace_type: tool_observation
source: hermes_terminal
session_id: session-20260805-001
profile_id: developer
project_id: external-zeromem
created_at: 2026-08-05T11:51:00+07:00
valid_from: 2026-08-05T11:51:00+07:00
valid_until: null
status: observed
verification: direct_tool_output
confidence: high
sensitivity: private
retention: persistent
content_ref: artifacts/tool/....json
hash: sha256:...
parent_trace_ids: [...]
replaces_trace_id: null
```

## 6.3. Claim - evidence - verification

```text
assistant_claim: "Index is complete"
    -> requires evidence
    -> file_count > 0
    -> index_version exists
    -> smoke_test passed
    -> exit_code = 0
    -> verified_state: "Index build completed and validated"
```

> Quy tắc: Không nâng assistant_claim thành active fact nếu không có tool observation, user confirmation hoặc deterministic verification.

# 7. Vòng đời memory, trạng thái và xung đột

## 7.1. Lifecycle state

| State | Ý nghĩa |
| --- | --- |
| raw | Mới ghi nhận, chưa chuẩn hóa |
| observed | Có nguồn trực tiếp nhưng chưa xác nhận ý nghĩa |
| candidate | Có khả năng hữu ích cho memory |
| confirmed | Đã được user/rule/tool xác nhận |
| active | Được dùng làm trạng thái hiện tại |
| superseded | Đã bị trạng thái mới thay thế |
| conflicted | Có bằng chứng mâu thuẫn chưa giải quyết |
| archived | Giữ lịch sử nhưng không ưu tiên |
| deleted | Đã xóa theo policy; giữ tombstone tối thiểu nếu cần |

## 7.2. Quy tắc cập nhật

- Raw trace không bị ghi đè; update tạo trace mới và liên kết replaces/supersedes.

- Active state chỉ có một bản hiện hành trong cùng entity + scope + state key, trừ khi trạng thái hỗ trợ nhiều giá trị.

- Tool failure cũ phải chuyển superseded khi fix đã được xác minh.

- Conflict không bị xóa; giữ cả hai claim, source và resolution record.

- Derived summary phải trỏ về source trace IDs và có thể rebuild.

## 7.3. Xử lý conflict

```text
Conflict detection:
1. Same entity + same attribute + overlapping valid time
2. Different values or incompatible states
3. Preserve all source traces
4. Rank by verification, source quality and temporal validity
5. If unresolved -> return conflict_set to Hermes
6. Hermes states uncertainty; no silent overwrite
```

# 8. Profile và hệ thống kiến thức

## 8.1. Profile là policy, không phải thư mục

Mỗi profile định nghĩa cách Hermes hành xử và cách memory substrate truy xuất. Knowledge space là một phạm vi dữ liệu; profile có thể ưu tiên nhiều space và vẫn có global access. Không cần tạo một Vault riêng cho mỗi profile nếu không có yêu cầu cách ly bảo mật.

## 8.2. Thành phần profile

| Nhóm policy | Ví dụ | Tác động |
| --- | --- | --- |
| Behavior | Coin68 neutral style, Quant analytical style | Cách viết và cấu trúc đầu ra |
| Knowledge priority | web3-research 1.0, editorial 0.9 | Xếp hạng corpus |
| Memory priority | current_project 1.0, verified_decision 1.0 | Xếp hạng trace |
| Access scope | global, isolated, explicit_union | Phạm vi được phép tìm |
| Tool policy | read-only, write-propose, terminal allowed | Quyền hành động |
| Privacy limit | private allowed, secret denied | Evidence được phép inject |
| Evidence budget | top_k, max tokens, neighbor limit | Kiểm soát context |
| Write policy | generated -> review -> curated | Cách ghi lại memory |

## 8.3. Chế độ truy xuất

- profile_first: tìm toàn hệ thống nhưng ưu tiên memory và knowledge của profile hiện tại.

- explicit_union: kết hợp các profile/knowledge space được người dùng chỉ định.

- isolated: chỉ dùng scope được chỉ định, không global fallback.

- global: bỏ profile priority hoặc dùng profile general để tìm toàn hệ thống.

- source_restricted: chỉ dùng file, project, session hoặc nguồn cụ thể.

## 8.4. Tách behavior khỏi knowledge

```text
behavior_profile: coin68-editor
knowledge_spaces:
  - quant-trading
  - engineering
memory_scope:
  - current_project
  - confirmed_decisions
access_mode: explicit_union
```

## 8.5. Cấu hình profile mặc định

```text
profile_id: general-assistant
default_access: global
retrieval_mode: profile_first
global_fallback: true
cross_profile_search: true
memory_priority:
  current_project: 1.00
  confirmed_decisions: 1.00
  verified_state: 1.00
  user_preferences: 0.90
  previous_sessions: 0.75
  unrelated_projects: 0.20
max_primary_evidence: 5
max_supporting_evidence: 3
max_evidence_tokens: 6000
```

# 9. Kiến trúc lưu trữ

## 9.1. Bốn lớp lưu trữ

| Lớp | Công nghệ tham chiếu | Chứa gì | Tính chất |
| --- | --- | --- | --- |
| Canonical trace | SQLite + JSONL | Event metadata, content refs, state, provenance | Append-first, queryable |
| Artifact store | File system | PDF, tool outputs, diffs, reports, attachments | Immutable/versioned |
| Retrieval index | FTS5 + FAISS/Qdrant + graph tables | Lexical, dense, temporal, relational index | Rebuildable |
| Obsidian Knowledge Workspace | Markdown Vault | Profiles, knowledge spaces, project state, decisions, curated research, conflict review | Human-readable, editable, rebuildable projection |

## 9.2. Schema bảng tối thiểu

```text
traces(trace_id, type, source, session_id, profile_id, project_id,
       created_at, valid_from, valid_until, status, verification,
       confidence, sensitivity, retention, content_ref, hash)

trace_links(from_trace_id, relation, to_trace_id)
entities(entity_id, entity_type, canonical_name)
entity_mentions(entity_id, trace_id, span_start, span_end)
tasks(task_id, project_id, status, current_step, updated_at)
decisions(decision_id, scope, state, rationale_ref, supersedes_id)
artifacts(artifact_id, path, mime_type, hash, version, created_at)
index_versions(index_id, kind, version, source_cutoff, built_at)
projection_links(trace_id, obsidian_path, projection_version)
```

## 9.3. Tính rebuildable

FTS, embeddings, graph edges và Obsidian projections phải có thể rebuild từ canonical trace và artifact store. Điều này cho phép thay model embedding, sửa schema hoặc khôi phục index mà không làm mất source-of-record.

# 10. Capture và ingestion pipeline

## 10.1. Observation-only capture

- Thu thập event nhưng chưa tự động inject vào prompt.

- Ghi session metadata, message, tool call/result, file read/write, skill usage, task transition và verification.

- Đo volume, duplicate, sensitivity, useful evidence rate và storage cost.

- Không tự động tạo permanent memory từ mọi event.

## 10.2. Capture flow chi tiết

```text
Hermes event
  -> event adapter
  -> secret/PII detector
  -> redact or reject
  -> schema validation
  -> content hash + duplicate check
  -> append raw trace
  -> deterministic metadata extraction
  -> FTS/vector/temporal/relational index update
  -> optional candidate memory classification
  -> optional Obsidian projection queue
```

## 10.3. Ingestion cho tài liệu

```text
File discovered
  -> checksum and version check
  -> extract text + page map + headings
  -> chunk with parent/neighbor IDs
  -> attach source locator and provenance
  -> local NER + embeddings + lexical index
  -> assign knowledge spaces by rule/metadata
  -> quality checks
  -> publish new index version
```

## 10.4. Deduplication

- Exact duplicate: content hash.

- Version duplicate: same logical artifact, new checksum/version.

- Near duplicate: normalized text hash hoặc MinHash; không xóa source.

- Projection duplicate: một trace chỉ có một curated projection hiện hành trong cùng namespace.

# 11. Retrieval, routing và context injection

## 11.1. Memory need router

| Route | Khi dùng | Ví dụ |
| --- | --- | --- |
| no_memory | Câu hỏi ổn định, không phụ thuộc lịch sử | Giải thích BM25 là gì |
| session_memory | Nhắc nội dung trong session hiện tại/gần nhất | Nãy mình đã quyết định gì? |
| project_memory | Tiếp tục project hoặc task | Tiếp tục xây Zero-Mem |
| user_memory | Preference hoặc environment ổn định | Dùng phong cách tôi thường viết |
| research_memory | Cần tài liệu/citation | So sánh paper đã lưu |
| global_memory | Cần kết hợp nhiều hệ thống | Dùng Quant + Engineering + Editorial |
| external_current | Thông tin có thể thay đổi sau cutoff | Kiểm tra phiên bản mới nhất |

## 11.2. Dual-view retrieval

1. Lexical/FTS lấy exact name, code, số liệu, date, path và phrase.

2. Dense retrieval lấy semantic similarity khi cách diễn đạt khác nhau.

3. Temporal view ưu tiên session/project state đúng thời điểm.

4. Relational view nối entity, decision, task, artifact và source.

5. Hierarchy/local span bổ sung parent, neighbor hoặc surrounding turn.

6. Profile and access policy áp scope filter trước final fusion.

## 11.3. Evidence score tham chiếu

```text
final_score = base_retrieval_score
            * profile_priority
            * memory_scope_weight
            * verification_weight
            * source_quality
            * temporal_validity
            * provenance_completeness
            * conflict_penalty
```

## 11.4. Controlled injection

- Không inject nếu route là no_memory.

- Chỉ inject evidence vượt confidence threshold và không vi phạm sensitivity.

- Mặc định top 5 primary + tối đa 3 support evidence.

- Context evidence mục tiêu 3.000-6.000 token; mở rộng theo request rõ ràng.

- Luôn gửi provenance, verification và state cùng nội dung.

- Nếu conflict hoặc insufficient evidence, Hermes phải thể hiện rõ.

## 11.5. Response envelope cho Hermes

```text
{
  "route": "project_memory",
  "active_profile": "developer",
  "used_scopes": ["external-zeromem", "confirmed-decisions"],
  "evidence": [
    {
      "trace_id": "...",
      "type": "verified_state",
      "content": "...",
      "source": "terminal",
      "timestamp": "...",
      "status": "active",
      "verification": "exit_code_0",
      "score": 0.93
    }
  ],
  "conflicts": [],
  "insufficient_evidence": false,
  "omitted_count": 18
}
```

# 12. Obsidian Knowledge Workspace và lớp projection

## 12.1. Vai trò trung tâm của Obsidian trong hệ thống

- Là không gian làm việc tri thức chính cho người dùng: đọc, audit, tổ chức và chỉnh sửa curated memory.

- Quản lý profile, knowledge space, glossary, learning path, research notes và tài liệu dự án trong một Vault thống nhất.

- Hiển thị Project Home, Decision Log, Current State, Conflict Queue, nguồn dẫn và trạng thái xác minh.

- Không thay thế canonical raw trace store; mọi event, tool output và bằng chứng gốc vẫn được giữ trong SQLite/JSONL và artifact store.

- Không tự mình thực hiện toàn bộ retrieval; FTS/vector/temporal/graph nằm ở sidecar, còn Obsidian cung cấp giao diện tri thức và control surface cho người dùng.

## 12.2. Một Vault thống nhất và cấu trúc namespace

```text
Knowledge-Vault/
  00-System/
    profiles/
    schemas/
    policies/
    runbooks/
  01-Shared/
    glossary/
    entities/
  10-Projects/
    external-zeromem/
    trading-agent/
  20-Decisions/
  30-Task-State/
  40-Research/
    quant-trading/
    web3/
  50-Preferences/
  60-Conflicts/
  80-Generated/
  90-Archive/
```

## 12.3. Chính sách projection và curated memory

- Chỉ candidate đã đạt điều kiện mới được đưa vào generated projection.

- Curated projection cần human approval hoặc deterministic verification policy.

- Mỗi note ghi trace_ids, source refs, status và projection_version.

- Khi raw trace thay đổi trạng thái, projection được update bằng phiên bản mới, không xóa lịch sử âm thầm.

Obsidian không phải phần phụ của hệ thống. Đây là lớp làm việc trực tiếp của người dùng đối với toàn bộ tri thức đã được xác minh, trong khi sidecar chịu trách nhiệm capture, indexing, retrieval và đồng bộ. Thiết kế này giữ được khả năng audit của Obsidian mà không buộc Vault phải chứa mọi log và event thô.

## 12.4. Mô hình dữ liệu note trong Obsidian

Mọi note do hệ thống tạo hoặc quản lý phải có metadata đủ để sidecar biết note thuộc profile, knowledge space, project và trạng thái nào. Metadata cũng phải trỏ ngược về trace gốc để có thể kiểm chứng và rebuild.

```text
---
note_id: note-uuid
note_type: project_state | decision | research | preference | conflict
profile_affinity:
  - developer
knowledge_spaces:
  - external-zeromem
project_id: hermes-external-zeromem
source_trace_ids:
  - trace-uuid-1
status: active
verification: verified
sensitivity: private
valid_from: 2026-08-05
valid_until: null
write_scope: current_project
projection_version: 3
---
```

## 12.5. Profile và Knowledge Space trong Obsidian

- Mỗi profile có một Profile Home chứa behavior policy, knowledge priority, memory priority, tool policy, privacy ceiling và evidence budget.

- Knowledge Space là namespace logic dựa trên folder và metadata; một note có thể thuộc nhiều space mà không cần sao chép file.

- Mặc định profile được phép đọc toàn Vault theo cơ chế profile-first; knowledge của profile hiện tại có trọng số cao hơn nhưng không khóa global access.

- Khi người dùng yêu cầu kết hợp, Hermes dùng explicit_union; khi yêu cầu chỉ dùng một corpus, hệ thống dùng isolated hoặc source_restricted.

- Behavior profile và knowledge scope luôn tách biệt, cho phép viết theo profile Coin68 nhưng dùng knowledge Quant hoặc Engineering.

| Chế độ | Phạm vi đọc trong Obsidian | Mục đích |
| --- | --- | --- |
| profile_first | Toàn Vault, ưu tiên profile/space hiện tại | Chế độ mặc định |
| explicit_union | Các profile/space được nêu rõ + shared | Kết hợp nhiều hệ thống kiến thức |
| isolated | Chỉ namespace được chỉ định | Đánh giá corpus hoặc tránh nhiễu |
| source_restricted | File, folder, project hoặc note cụ thể | Bài viết/kiểm chứng theo nguồn giới hạn |

## 12.6. Luồng đồng bộ hai chiều

Obsidian được phép chỉnh sửa curated knowledge nhưng không được ghi đè raw trace. Mọi thay đổi từ Vault phải đi qua hàng đợi kiểm tra trước khi cập nhật canonical state.

```text
Đọc / projection:
SQLite + JSONL + artifact store
  -> projection generator
  -> Markdown notes + YAML metadata
  -> Obsidian Vault

Ghi / review:
User edits curated note in Obsidian
  -> change queue
  -> schema + permission + conflict validation
  -> approved write-back record
  -> canonical state update
  -> regenerate projection
```

- Raw trace luôn append-first; sửa note chỉ tạo write-back event hoặc decision mới.

- Nếu note bị sửa khác với verified state, hệ thống tạo conflict thay vì âm thầm chọn một bên.

- Projection generator phải idempotent và có projection_version để không tạo note trùng.

- Người dùng có thể đánh dấu candidate thành confirmed, resolve conflict hoặc supersede quyết định qua workflow có audit.

## 12.7. Các trang vận hành bắt buộc trong Vault

| Trang / khu vực | Nội dung | Nguồn dữ liệu |
| --- | --- | --- |
| System Home | Health, index version, capture status, pending review | Sidecar metrics + projection state |
| Profile Home | Behavior, knowledge priority, access/write policy | Profile configuration |
| Project Home | Objective, active requirements, current verified state, next action | Project capsule |
| Decision Log | Active, superseded và conflicted decisions | Decision traces / ADR |
| Task State | Completed, in progress, blocked, verification | Task state records |
| Candidate Review | Memory chờ xác nhận hoặc phân loại | Candidate queue |
| Conflict Queue | Claims mâu thuẫn, source và resolution | Conflict records |
| Knowledge Space Index | Nguồn, chủ đề, entity và liên kết | Curated research + indexes |

## 12.8. Dữ liệu nên và không nên nằm trong Obsidian

| Nên lưu trong Vault | Không nên lưu trực tiếp trong Vault |
| --- | --- |
| Profile, policy và runbook đã duyệt | API key, OAuth token, private key hoặc password |
| Project charter, requirement và decision log | Toàn bộ stdout/stderr hoặc log dung lượng lớn |
| Current verified state và task summary có provenance | Raw event stream theo từng mili-giây |
| Curated research note, glossary, source map và learning path | Embedding vector và graph index nhị phân |
| Conflict record và resolution đã audit | File tạm, cache hoặc dữ liệu never_store |
| Link/ID tới raw artifact và trace gốc | Assistant claim chưa xác minh được coi như fact |

## 12.9. Điều kiện nghiệm thu riêng cho Obsidian

- Một Vault duy nhất mở được bình thường trên Obsidian và không phụ thuộc vào plugin để đọc nội dung cốt lõi.

- 100% note do hệ thống tạo có note_id, note_type, source_trace_ids, status, verification, sensitivity và projection_version.

- Profile Home và Project Home phản ánh đúng config/current verified state từ canonical store.

- profile_first, explicit_union, isolated và source_restricted trả đúng phạm vi trong benchmark.

- Thay đổi note được đưa vào review queue; không có direct overwrite đối với raw trace.

- Vault không chứa secret trong security test và có thể rebuild hoàn toàn từ canonical store + curated write-back records.

- Obsidian và sidecar không tạo vòng lặp đồng bộ hoặc note trùng khi chạy projection nhiều lần.

# 13. Tích hợp Hermes qua Sidecar và MCP

## 13.1. Nguyên tắc tích hợp

- Sidecar lắng nghe event và cung cấp retrieval API; Hermes core thay đổi tối thiểu.

- Tool schema phải nhỏ, ổn định và trả structured error.

- Read-only retrieval triển khai trước write-back.

- Native memory chỉ giữ cấu hình ngắn: default profile, endpoint và user preferences ổn định.

## 13.2. MCP tools tối thiểu

| Tool | Mục đích | Giai đoạn |
| --- | --- | --- |
| zero_mem.search | Tìm evidence theo query, profile, scope, time | MVP |
| zero_mem.get_trace | Lấy raw/expanded trace theo ID | MVP |
| zero_mem.get_task_state | Lấy trạng thái project/task hiện tại | MVP |
| zero_mem.get_decisions | Lấy decision active/superseded/conflicted | MVP |
| zero_mem.expand | Mở neighbor, parent hoặc graph bridge | Sau MVP |
| zero_mem.propose_memory | Đề xuất candidate memory, chưa curate | Sau MVP |
| zero_mem.project_to_obsidian | Tạo/update projection theo policy | Sau MVP |

## 13.3. Request mẫu

```text
{
  "query": "Tiếp tục xây hệ thống external memory",
  "active_profile": "developer",
  "memory_route": "project_memory",
  "project_id": "external-zeromem",
  "knowledge_spaces": ["engineering", "agent-memory"],
  "access_mode": "profile_first",
  "global_fallback": true,
  "top_k": 5,
  "include_neighbors": true,
  "require_provenance": true
}
```

# 14. Bảo mật, quyền riêng tư và quản trị

## 14.1. Sensitivity classes

| Class | Ví dụ | Policy mặc định |
| --- | --- | --- |
| public | Public paper, public documentation | Persist và search được |
| internal | Project notes, local paths | Persist, chỉ user/profile được phép |
| private | Email content, personal preference | Persist có encryption/access policy |
| secret | API key, token, password, private key | Không persist; redact/reject ngay |

## 14.2. Redaction trước persist

- Detect credential patterns, bearer tokens, private keys, passwords và OAuth secrets.

- Không lưu raw secret rồi mới xóa sau; redaction/rejection phải ở capture boundary.

- Ghi audit event rằng dữ liệu đã bị redacted nhưng không ghi giá trị gốc.

- Tool output lớn có thể lưu file encrypted và chỉ index metadata/approved excerpts.

## 14.3. Retention và delete

- temporary: tự xóa sau thời hạn.

- session: giữ đến khi session/project đóng.

- persistent: giữ theo user policy.

- never_store: chỉ xử lý trong RAM và không persist.

- Delete request phải xóa raw, artifact, index và projection; index dùng tombstone/versioning để tránh orphan.

## 14.4. Governance

- Schema migration có version và rollback.

- Write-back luôn có audit log.

- Profile không tự tăng quyền.

- Curated memory có owner và review timestamp.

- Benchmark và security test chạy trước mỗi release lớn.

# 15. Chiến lược tiết kiệm token

## 15.1. Nguồn tiết kiệm chính

1. Không gửi lại toàn bộ conversation history.

2. Không đưa tool output cũ vào context trừ khi liên quan.

3. Không load toàn bộ skill/corpus cho mỗi turn.

4. Không gọi LLM để tạo memory sau mỗi event.

5. Không tóm tắt lặp lại summary cũ; giữ raw trace và index cục bộ.

6. Chỉ final evidence set đi vào LLM.

7. Task state và decision nằm ngoài context để có thể tiếp tục session mới.

## 15.2. Ngân sách đề xuất

| Hạng mục | Mặc định | Ghi chú |
| --- | --- | --- |
| Primary evidence | 5 units | Có thể tăng cho multi-hop |
| Supporting evidence | Tối đa 3 units | Neighbor/bridge chỉ khi cần |
| Evidence tokens | 3.000-6.000 | Không bao gồm final answer |
| Memory-operation LLM calls | 0 | Mục tiêu kiến trúc |
| Search retries | 1 lần mở rộng | Sau đó báo insufficient evidence |
| Projection write | Theo batch hoặc event quan trọng | Không mỗi turn |

## 15.3. Metrics

- LLM input/output tokens per query.

- Memory-operation LLM calls (mục tiêu 0).

- Retrieved evidence tokens và omitted count.

- Retrieval latency p50/p95.

- Recall@K, MRR/nDCG và citation accuracy.

- Task continuation success rate.

- Conflict detection rate và stale-state error rate.

# 16. Cách xây dựng chi tiết

## 16.1. Stack kỹ thuật đề xuất

| Khối | Lựa chọn MVP | Nâng cấp sau |
| --- | --- | --- |
| Runtime | Python 3.11+, FastAPI hoặc local MCP | Rust service nếu cần hiệu năng |
| Trace DB | SQLite + WAL + FTS5 | PostgreSQL khi multi-user |
| Raw event | JSONL per day/session | Object storage |
| Vector | FAISS local | Qdrant local/server |
| Embedding | BGE-M3 hoặc multilingual local | Domain-tuned embedding |
| NER | spaCy + regex + dictionaries | Domain entity linker |
| Graph | SQLite edge tables + NetworkX batch | Neo4j only when justified |
| Projection | Obsidian Markdown | Custom dashboard sau |
| Integration | MCP/local HTTP | Hermes native plugin sau |

## 16.2. Repository structure

```text
external-zeromem/
  ARCHITECTURE.md
  config/
    profiles/
    policies/
    schemas/
  src/
    capture/
    redaction/
    storage/
    indexing/
    routing/
    retrieval/
    calibration/
    projection/
    mcp/
  migrations/
  tests/
    unit/
    integration/
    benchmark/
  data/
    traces/
    artifacts/
    indexes/
    obsidian_workspace/
      vault/
      projection_state/
  scripts/
  runbooks/
  pyproject.toml
  README.md
```

## 16.3. Thứ tự xây dựng module

1. Schema và migration.

2. Event adapter và redaction.

3. Canonical trace store và artifact store.

4. FTS retrieval có provenance.

5. Task/decision state queries.

6. Profile resolver và access policy.

7. Vector retrieval và fusion.

8. MCP integration.

9. Controlled injection.

10. Graph, temporal hierarchy và Obsidian projection.

## 16.4. Definition of Done cho mỗi module

- Có schema và migration.

- Có unit test và failure case.

- Có structured log và metrics.

- Có provenance output.

- Có security/redaction test nếu xử lý content.

- Có tài liệu runbook và rollback.

# 17. Kiểm thử và tiêu chí nghiệm thu

## 17.1. Bộ test bắt buộc

| Nhóm test | Mục tiêu | Ví dụ |
| --- | --- | --- |
| Capture | Không mất event, đúng order và timestamp | Tool call + result linked |
| Redaction | Không persist secret | Bearer token removed |
| Provenance | Mọi evidence có source locator | trace_id + artifact hash |
| State | Không dùng lỗi đã superseded | Fix mới được ưu tiên |
| Profile isolation | Isolated không leak scope | Quant không lấy Web3 |
| Global combination | Explicit union lấy đúng nhiều space | Quant + Engineering |
| Retrieval | Gold evidence nằm top-k | Recall@5 |
| Conflict | Không overwrite claim mâu thuẫn | Hai funding values |
| Task continuation | Tiếp tục đúng step sau session mới | Unresolved state recovered |
| Token | Context giảm so baseline | Evidence-only vs full history |

## 17.2. Tiêu chí nghiệm thu MVP

- Capture thành công ít nhất 99% event trong test harness; lỗi có retry hoặc dead-letter record.

- 100% evidence có trace_id, source, timestamp, status và verification.

- Secret test corpus không xuất hiện trong raw store hoặc index.

- Profile isolated mode không trả evidence ngoài scope.

- Task continuation trả đúng current step trong ít nhất 90% test scenario.

- Memory-operation LLM calls bằng 0.

- p95 retrieval dưới ngưỡng đã đặt cho máy local; đề xuất ban đầu < 2 giây cho MVP.

- Evidence token trung bình giảm rõ so với full-history baseline.

## 17.3. Benchmark nội bộ

- 50-100 câu hỏi gồm single-hop, multi-hop, temporal, exact fact, project continuation và conflict.

- Gold evidence và expected state, không chỉ gold answer.

- So sánh FTS, dense, hybrid, hybrid + temporal và hybrid + graph.

- Đo Recall@K, nDCG, citation accuracy, groundedness, stale-state rate, latency và token.

# 18. Lộ trình triển khai

Lộ trình được thiết kế theo nguyên tắc giảm rủi ro: quan sát trước, truy xuất read-only sau, chỉ inject có kiểm soát khi dữ liệu và benchmark đủ tốt. Thời lượng tham chiếu 10-14 tuần cho một người triển khai tập trung; corpus lớn được đưa vào sau khi pipeline memory ổn định.

| Giai đoạn | Thời lượng | Đầu ra chính | Cổng nghiệm thu |
| --- | --- | --- | --- |
| 0. Policy & Architecture | 1 tuần | ARCHITECTURE.md, schema, sensitivity, retention, benchmark plan | Kiến trúc được chốt |
| 1. Observation-only Sidecar | 1-2 tuần | Event capture, redaction, JSONL/SQLite | Không mất event, không lưu secret |
| 2. Canonical Store | 1 tuần | Trace DB, artifact store, migrations, backup | Rebuild được metadata |
| 3. Read-only Retrieval | 1-2 tuần | FTS search, get_trace, task/decision queries | Gold evidence top-k |
| 4. Query Routing | 1 tuần | no/session/project/user/research/global routes | Route accuracy đạt ngưỡng |
| 5. Profile System | 1 tuần | profile-first, explicit, isolated, global | Isolation và priority test pass |
| 6. MCP + Hermes | 1 tuần | zero_mem tools, structured errors | Hermes gọi được read-only memory |
| 7. Controlled Injection | 1 tuần | Evidence budget, confidence gate, conflict set | Không inject sai scope |
| 8. Graph/Temporal/Calibration | 1-2 tuần | Entity links, state hierarchy, closure | Multi-hop/temporal cải thiện |
| 9. Obsidian Projection | 1 tuần | Curated project/decision/research views | Audit và update ổn định |
| 10. Corpus Expansion | Liên tục | 600 PDF và domain knowledge systems | Batch QA đạt chuẩn |

## 18.1. Việc làm ngay trong giai đoạn 0

1. Tạo ARCHITECTURE.md làm source of truth từ tài liệu này.

2. Chốt taxonomy trace, provenance envelope và lifecycle state.

3. Viết danh sách dữ liệu never_store và redaction patterns.

4. Chọn 3 profile đầu: general-assistant, developer, quant-researcher hoặc coin68-editor.

5. Tạo 30-50 scenario benchmark, ưu tiên task continuation và stale-state.

6. Chưa ingest toàn bộ 600 PDF; chỉ dùng corpus nhỏ khi test research route.

# 19. Vận hành sau triển khai

## 19.1. Chu kỳ vận hành

- Hằng ngày: health check, failed event queue, storage growth và secret alert.

- Hằng tuần: review candidate memories, conflicts, stale active state và index lag.

- Hằng tháng: backup restore test, benchmark regression và profile policy audit.

- Khi đổi embedding/schema: tạo index version mới, chạy benchmark, rồi switch atomically.

## 19.2. Quy trình thêm profile

1. Xác định use case và behavior thực sự khác biệt.

2. Đặt memory/knowledge priorities, access scope, privacy ceiling và tool policy.

3. Tạo 10-20 test query đại diện.

4. Chạy isolation, global fallback, conflict và evidence budget tests.

5. Version profile config và phát hành.

## 19.3. Quy trình thêm knowledge system

1. Định nghĩa scope và metadata rule.

2. Ingest corpus mẫu, không sao chép source nếu có thể gán multi-space.

3. Đặt source quality và temporal validity policy.

4. Tạo benchmark chống nhầm với knowledge system gần nhất.

5. Gắn vào profile priorities và theo dõi retrieval drift.

# 20. Rủi ro và biện pháp xử lý

| Rủi ro | Hậu quả | Biện pháp |
| --- | --- | --- |
| Capture quá nhiều | Storage và noise tăng | Observation metrics, retention, candidate gate |
| Lưu secret | Rò rỉ nghiêm trọng | Redaction/reject trước persist, security tests |
| Assistant claim thành fact | Tiếp tục task sai | Verification weighting và state gate |
| Stale state | Dùng lỗi/quyết định cũ | valid time, superseded và temporal retrieval |
| Profile leak | Lấy dữ liệu sai phạm vi | Scope filter trước retrieval, isolation tests |
| Over-retrieval | Token tăng và nhiễu | Top-k, evidence budget, closure limit |
| Under-retrieval | Thiếu điều kiện quan trọng | Neighbor/bridge expansion và insufficiency flag |
| Obsidian thành source duy nhất | Mất raw event và khó scale | Canonical store tách biệt |
| Index corruption | Recall giảm | Versioned indexes, rebuild và atomic switch |
| Graph quá phức tạp sớm | Chậm tiến độ | FTS + temporal MVP trước graph nâng cao |

# 21. Cấu hình mặc định và bước bắt đầu

## 21.1. Cấu hình mặc định đề xuất

```text
canonical_trace_store: sqlite_jsonl
artifact_store: local_versioned_files
obsidian_role: knowledge_workspace_and_curated_projection
capture_mode: observation_only
memory_operation_llm_calls: 0
default_profile: general-assistant
default_access: global
default_retrieval: profile_first
global_fallback: true
require_provenance: true
require_verification_for_active_state: true
redact_before_persist: true
max_primary_evidence: 5
max_supporting_evidence: 3
max_evidence_tokens: 6000
write_policy: propose_then_review
```

## 21.2. Quyết định thực thi đầu tiên

> Bước đầu tiên: Tạo ARCHITECTURE.md và observation-only sidecar skeleton. Chưa xây RAG cho toàn bộ PDF, chưa inject memory tự động và chưa sửa sâu Hermes core.

## 21.3. Kết luận

Thiết kế phù hợp nhất là một memory substrate bên ngoài cho toàn Hermes, kết hợp với một Obsidian Knowledge Workspace duy nhất để người dùng quản lý profile, knowledge space, project, quyết định, trạng thái công việc và tri thức đã được xác minh. SQLite/JSONL giữ canonical raw trace; Obsidian giữ lớp tri thức đọc được, chỉnh sửa được và có kiểm soát. Giá trị lớn nhất đến từ khả năng tiếp tục dự án dài bằng verified state, provenance và retrieval có giới hạn thay vì phụ thuộc vào summary của LLM.

# Phụ lục A-G

## Phụ lục A - Mẫu trace JSON

```text
{
  "trace_id": "uuid",
  "trace_type": "tool_observation",
  "source": "terminal",
  "session_id": "...",
  "profile_id": "developer",
  "project_id": "external-zeromem",
  "created_at": "2026-08-05T11:51:00+07:00",
  "status": "observed",
  "verification": "direct_tool_output",
  "confidence": "high",
  "sensitivity": "private",
  "retention": "persistent",
  "content_ref": "artifacts/tool/....json",
  "hash": "sha256:...",
  "links": [
    {"relation": "result_of", "trace_id": "tool-call-id"}
  ]
}
```

## Phụ lục B - Mẫu profile YAML

```text
profile_id: coin68-editor
behavior_profile: coin68-editor
knowledge_priority:
  coin68-editorial: 1.00
  web3-research: 0.95
  shared: 0.80
  other: 0.50
memory_priority:
  current_project: 1.00
  confirmed_decisions: 1.00
  verified_state: 1.00
  research_sources: 0.95
  previous_sessions: 0.75
default_access: global
retrieval_mode: profile_first
allow_cross_profile: true
privacy_ceiling: private
write_policy: propose_only
max_evidence_tokens: 6000
```

## Phụ lục C - Mẫu MCP response

```text
{
  "evidence": [],
  "conflicts": [],
  "route": "project_memory",
  "active_profile": "developer",
  "used_scopes": [],
  "insufficient_evidence": false,
  "index_version": "2026-08-05.1",
  "latency_ms": 183,
  "omitted_count": 0
}
```

## Phụ lục D - Checklist trước khi code

- Đã chốt canonical store và Obsidian role.

- Đã chốt trace taxonomy và provenance envelope.

- Đã chốt state lifecycle và conflict policy.

- Đã viết never_store và redaction rules.

- Đã chọn profile đầu tiên và benchmark scenarios.

- Đã xác định event sources Hermes có thể xuất.

- Đã có backup/restore plan cho SQLite, JSONL và artifacts.

- Đã chốt observation-only, chưa controlled injection.

## Phụ lục E - Checklist trước controlled injection

- Redaction tests pass.

- Profile isolation tests pass.

- Task continuation benchmark đạt ngưỡng.

- Stale-state và superseded tests pass.

- Evidence có provenance 100%.

- Latency và token metrics đã có baseline.

- Có kill switch để tắt automatic memory injection.

## Phụ lục F - Bộ câu hỏi benchmark mẫu

- Trước đây đã chọn canonical store nào và vì sao?

- Task hiện tại đang dừng ở bước nào và bước nào chưa xác minh?

- Lỗi Docker login cũ còn active hay đã superseded?

- Chỉ dùng profile Quant: tài liệu nào định nghĩa walk-forward validation?

- Kết hợp Quant + Engineering: đề xuất cách tổ chức research agent.

- Hai nguồn đưa số funding khác nhau: conflict nằm ở đâu?

- Câu trả lời assistant nói file đã tạo, tool evidence có xác nhận không?

- Tìm quyết định mới nhất về vai trò của Obsidian.

## Phụ lục G - Tài liệu tham chiếu

- R1. Xiao, Y. và cộng sự. "Zero-Mem: Zero-Token Memory Operations for LLM Agents." arXiv:2607.29377v1, 31/07/2026.

- R2. Yêu cầu do người dùng cung cấp: External Zero-Mem layer cho toàn bộ Hermes Agent.

- R3. Yêu cầu do người dùng cung cấp: mỗi profile có knowledge system riêng, có thể kết hợp theo yêu cầu và mặc định được phép truy cập toàn cục theo cơ chế profile-first.

Quay lại Mục lục
