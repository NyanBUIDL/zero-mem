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
[ ] SCOUT: corpus-derived.sqlite tồn tại? source/unit counts hiện tại?
[ ] SCOUT: đối chiếu với mục tiêu 600 md + 471 pdf → gap chính xác
[ ] SCOUT: preconditions prompt quant_lab nào đã stale (v1.3.0 refs)?
[ ] BUILDER: cập nhật prompt preconditions + ghi V140 overlay vào project-state
[ ] Gap-analysis report trình GATE-0
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
```

## V140-02 — ADR DEF-004 knowledge-space resolution

```
[ ] SCOUT: impact-set Graphify cho cả 2 phương án A/B
[ ] ADR draft: so sánh A (migration v13 column) vs B (resolution layer) —
    storage cost, rebuildability, migration risk, token cost
[ ] USER chọn phương án tại GATE-2 (bằng văn bản)
[ ] Implement theo phương án được duyệt (RED-first nếu code product)
[ ] Migration test nếu chọn A; resolution tests nếu chọn B
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
