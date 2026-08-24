# v1.4.0 — Checklist thực thi

> Hai tầng: **CHECKLIST GỐC** áp dụng 100% cho mọi WP; **CHECKLIST RIÊNG** đo mục tiêu đặc thù từng WP.
> SCRIBE copy trạng thái tick vào handoff cuối mỗi Gate. Tick chỉ khi có evidence vật lý.

---

## CHECKLIST GỐC (mọi WP, không ngoại lệ)

```
[ ] SCOUT report hoàn tất TRƯỚC khi Builder gõ phím
[ ] Scope chốt bằng văn bản: file được sửa / file cấm đụng
[ ] RED-first test nếu đụng code product src/
[ ] Focused test PASS + evidence nguyên văn (lệnh + output)
[ ] Full suite PASS (baseline hiện hành, isolated HOME)
[ ] Self-review: architecture / canonical-vs-derived / provenance /
    token-storage cost / failure path
[ ] VERIFIER độc lập (subagent tách session) xác nhận — verdict nguyên văn
[ ] Handoff Markdown theo template (Observed/Changed/Verified/Risk/Next/Authorization)
[ ] project-state.yaml overlay cập nhật (V140-xx_status)
[ ] Commit tham chiếu đúng ID (V140-xx / DEF-xxx)
```

---

## V140-00 — Re-baseline & recon

```
[x] SCOUT: corpus-derived.sqlite tồn tại? source/unit counts hiện tại?
    → DB 123MB; zm_corpus_sources=1070, zm_corpus_units=9863, zm_corpus_fts=9863;
      kinds: primary-pdf 471 / derived-md 470 / orphan-md 129; ks: quant-theory 100%.
      Evidence: artifacts/handoffs/V140-00-HANDOFF.md (Scout report §1–2)
[x] SCOUT: đối chiếu với mục tiêu 600 md + 471 pdf → gap chính xác
    → PDF: 471/471 đủ, extract OK 471/471 (9 863 units). MD: 599 article-md đã
      register + 0 units; file md thứ 600 nằm trong papers/ (mirror hỏng của
      cond-mat_0210475, text garbage — không đăng ký là đúng). Gap V140-01 =
      extract units cho 599 md-sources. Evidence: handoff §Gap analysis.
[x] SCOUT: preconditions prompt quant_lab nào đã stale (v1.3.0 refs)?
    → v1.3.0/14e52ff/release-gate refs stale → Builder re-baseline sang v1.3.4/789db91.
[x] BUILDER: cập nhật prompt preconditions + ghi V140 overlay vào project-state
    → CORPUS-QUANT-LAB-PROMPT.md (header, Current state section, QL-1 note,
      Bước 0); project-state.yaml v140_status/v140_00_status overlay.
[x] Gap-analysis report trình GATE-0
    → artifacts/handoffs/V140-00-HANDOFF.md; Verifier verdict nguyên văn: PASS.
```

## V140-01 — Ingest quant_lab

```
[ ] SCOUT dry-run: đếm source/unit/skip dự kiến từng nhóm (md/pdf)
[ ] Số source = mục tiêu hoặc chênh lệch được giải thích bằng văn bản
[ ] Phân loại đủ 3 nhóm: primary-pdf / derived-md / orphan-md (~130)
[ ] Idempotency: chạy lần 2 → 0 source mới (log bằng chứng)
[ ] Verbatim spot-check ≥10 units khớp PDF gốc CHỮ
[ ] FTS smoke: "Kelly criterion" / "limit order book" / "rough volatility" trả hit hợp lý
[ ] Skip list tường minh kèm lý do từng file (KHÔNG skip im lặng)
[ ] git status sạch sau khi chạy (không corpus vào repo)
[ ] Tooling nhận --source-dir/--ks-name/--adapter (generic — GATE-0-ADDENDUM)
[ ] arxiv-quant là adapter instance, không hardcode (GATE-0-ADDENDUM)
```

## V140-02 — ADR DEF-004 knowledge-space resolution

```
[x] SCOUT: impact-set Graphify cho cả 2 phương án A/B
    → graphify-out/ (8719 nodes) + corroborated source (commit 5a99ce4).
[x] ADR draft: so sánh A (migration v13 column) vs B (resolution layer)
    → docs/v1.4/ADR-V140-01-DEF004.md. GATE-2 CHỌN B (no zm_meta schema change).
[x] Implement theo B (resolution layer):
    - src/access/knowledge_space_resolver.py (resolve space->(profile,project)
      từ zm_corpus_sources/units, derived/rebuildable).
    - src/access/authorized_read.py: _scope_allows nhận space_members param
      (fail-closed khi None); facade AuthorizedReadService.corpus_conn +
      _expand_scope_with_spaces gắn members vào scope profile/project.
    - KHÔNG migrate_13, zm_meta schema UNCHANGED (tuân thủ GATE-2).
[x] RED-first test: space-grant authorizing event-read đúng; fail-closed khi
    ks không map → test_v140_02_ks_resolution.py (9 tests, RED→GREEN).
[x] Full suite (isolated HOME, Py 3.13.15): 3412 passed, 7 skipped, 0 failed.
[x] Verifier độc lập PASS (GATE-2b chờ duyệt).
```

## V140-03 — MCP adapter + import tool

```
[ ] SCOUT: M6 surface survey + thiết kế điểm cắt MCP server
[ ] MCP server wrapper implement (tái dùng M6 dispatcher, không fork core)
[ ] Import CLI tool hoạt động offline
[ ] POC: MCP client KHÔNG-PHẢI-Hermes query knowledge base OK
    (verifier ngoài thực hiện — chống xung đột lợi ích)
[ ] Demo script tái lập được POC từ máy sạch
[ ] Authorization-first giữ nguyên qua MCP path (grant/resource-type isolation test)
```

## V140-04 — Retrieval-quality benchmark

```
[ ] QA held-out set ≥30 câu từ quant_lab (không trùng training-ish queries)
[ ] precision@k harness stdlib-only, deterministic (seed cố định nếu sampling)
[ ] ≥2 runs trùng kết quả (reproducibility proof)
[ ] Baseline số liệu ghi vào EVIDENCE.md + so sánh baseline tổng hợp cũ (recall@8 0.519 N=500)
[ ] Kết quả là INPUT cho quyết định v1.5 semantic — không tự đề xuất v1.5 trong WP này
```

## V140-05 — Closure

```
[ ] EVIDENCE.md tổng hợp đầy đủ verdicts mọi Gate
[ ] RELEASE-NOTES-v1.4.0.md theo format v1.3.x
[ ] Full suite cuối PASS trên HEAD candidate
[ ] Preflight publication (remote verify, tag khớp commit)
[ ] GATE-FINAL duyệt → tag v1.4.0 + GH Release
[ ] Gates file mv vào _gates-done/v1.4.0/ + WORKSPACE-POLICY inventory refresh
```

---

## Gate log (điền khi duyệt)

| Gate | Ngày | Quyết định | Evidence tham chiếu |
|---|---|---|---|
| GATE-0 | | | |
| GATE-1 | | | |
| GATE-2 (chọn A/B) | | | |
| GATE-2b | | | |
| GATE-3 | | | |
| GATE-4 | | | |
| GATE-FINAL | | | |
