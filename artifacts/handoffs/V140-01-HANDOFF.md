# V140-01 HANDOFF — Ingest hoàn tất quant_lab (md units + generic tooling)

- **WP:** V140-01 (v1.4.0) — md unit extraction + GATE-0-ADDENDUM generic tooling
- **Ngày:** 2026-08-24 · **Repo:** zero-mem-v123-engineering @ `69c6265` (master = GitHub, local)
- **Authorization:** GATE-0-APPROVAL.md + GATE-0-ADDENDUM.md (user paste) — local only, KHÔNG push
- **Phases:** SCOUT dry-run → APPLY (commit `edae9e1`) → idempotency re-run → VERIFIER (subagent) → SCRIBE/GATE-1

## Observed

### DB state sau apply (corpus-derived.sqlite, read-only verified)
| Metric | Giá trị |
|---|---|
| zm_corpus_sources | 1070 (primary-pdf 471 / derived-md 470 / orphan-md 129), ks 100% quant-theory |
| zm_corpus_units | **217,256** (pdf 9,863 + md 207,393) |
| zm_corpus_fts | 217,256 (index đầy đủ) |
| blob_ref | 1070/1070 non-null (rebind fix) |
| duplicate (external_ref,kind) | 0 |
| units/source kind | derived-md 153,987 · orphan-md 53,406 · primary-pdf 9,863 |

### Root cause đã fix
V140-00 recon: 599 md-sources có 0 units vì `blob_back_md_sources()` ghi 599
blob nhưng KHÔNG rebind `blob_ref` vào registry → `project_corpus` skip (blob_ref
None). Fix: dùng `register_source_with_blob()` (dedup-safe, rebind đúng) qua
`corpus_md_extract_apply.py`. Kết quả: 599 md sources → 207,393 units.

### Quality / skip
- Skip-list GATE-0: `papers/2002-10-22 - cond-mat_0210475 - ....md` (garbage-ocr-mirror)
  = expected-skip, KHÔNG có trong registry. Tổng disk = 599 article-md + 471 pdf + 1 skip.
- md quality dry-run: 599/599 đạt (no garbage, không skip ngoài entry trên).

## Changed (commits local, KHÔNG push)
- `edae9e1` — `scripts/corpus_md_extract_dry_run.py`, `scripts/corpus_md_extract_apply.py`,
  `scripts/corpus_skip_list.json` (md extraction + skip-list + blob_ref rebind + projection).
- `69c6265` (GATE-0-ADDENDUM) — `scripts/adapters/arxiv_quant_adapter.py` (adapter instance),
  `scripts/corpus_generic_ingest.py` (parameterized: --source-dir/--ks-name/--adapter/--skip-list/--project),
  `README.md` + `docs/v1.4/CHECKLIST.md` sync (quant_lab = sample corpus).
- `V140-00` từ `a53ce2d`.

Không đụng `src/` (tooling-only). DB backup: `corpus-derived.sqlite.bak-v140-00`.

## Verified (Verifier độc lập `deleg_b69b3bca` → OVERALL: PASS 10/10)
1. units 217,256 (split 9863/153987/53406) ✓
2. FTS 217,256 ✓
3. sources 1070, ks 100%, blob_ref 1070/1070 ✓
4. idempotency 0 dup ✓
5. md verbatim 20/20 substring khớp source .md ✓
6. pdf verbatim 8/8 whitespace-normalized khớp page PDF (pymupdf) ✓
7. FTS smoke 18 / 1643 / 984 ✓
8. skip-list entry đúng + file vắng mặt trong registry ✓
9. git working tree chỉ chứa tooling/doc đúng, src/ untouched ✓
10. generic tool + arxiv-quant adapter instance (không hardcode) ✓

Idempotency apply lần 2: `new_sources=0`, `units_projected=207,393` (bằng lần 1).

## Gap / Next (trình GATE-1)
- **(a)/(b) decision (GATE-0-ADDENDUM):** đề xuất **(a)** — generic tool + adapter đã
  viết xong, dry-run qua (`dirs=600`, parse đúng). Không rework DB. Maintainer duyệt (a) hoặc (b).
- PDF extraction + full-apply phase CHƯA viết → bắt buộc tham số hóa (đã sẵn sàng qua
  `corpus_generic_ingest.py --project`).
- Sau GATE-1 PASS: V140-02 (ADR DEF-004 ks-resolution) theo ROADMAP.
- **DỪNG chờ GATE-1** — không tự chuyển V140-02.

## Authorization
Local-only theo prompt user. Chưa push. 3 commits (`a53ce2d`, `edae9e1`, `69c6265`)
chờ maintainer duyệt GATE-1 + quyết định (a)/(b) trước khi release/push.
