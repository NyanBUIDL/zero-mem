# Zero-Mem — Documentation Index (docs/)

`docs/` là nơi quy hoạch và ghi lại mọi khía cạnh phát triển của Zero-Mem theo **từng version**:

- **Lộ trình** — định hướng version này làm gì, phạm vi, ngoài phạm vi, thứ tự công việc.
- **Hướng phát triển** — quyết định kiến trúc, ràng buộc không được phá, lý do.
- **Cách phát triển** — quy trình, giao thức agent, gate kiểm thử, điều kiện dừng, template work-package.
- **Công nghệ** — stack đã duyệt, thứ gì cố ý không dùng.
- **Bằng chứng phát triển** — evidence, work-packages, acceptance, audit theo từng version.

> **Nguyên tắc:** `docs/` chứa quy hoạch + bằng chứng. Bản thân `docs/` không phải canonical data
> (canonical = JSONL event + artifact). Evidence trong `docs/` là **lịch sử bất biến**:
> không sửa nội dung đã nghiệm thu; nếu cần ghi đè kết luận, viết tài liệu/supersede mới.

---

## Cấu trúc chuẩn theo version

Mỗi version hoạt động có thư mục `docs/vX.Y.Z/` với khung sau (xem `docs/VERSION-TEMPLATE.md`):

```text
docs/
  README.md                  <- index này
  VERSION-TEMPLATE.md         <- khung tạo version mới
  architecture/               <- tài liệu kiến trúc xuyên version (mục tiêu ổn định)
  governance/                 <- GITHUB-POLICY và các chính sách bắt buộc
  acceptance/                 <- acceptance theo milestone (M0..M10)
  plans/                      <- kế hoạch milestone/phase
  audits/                     <- audit tổng hợp
  runbooks/                   <- vận hành
  reference/                  <- tham chiếu
  vX.Y.Z/
    README.md                 <- index version (bắt buộc)
    ROADMAP.md                <- lộ trình version (bắt buộc; v1.2.4 dùng MASTER_PLAN.md)
    ARCHITECTURE.md           <- kiến trúc version (bắt buộc)
    TECH_STACK.md             <- công nghệ version (bắt buộc)
    DEVELOPMENT.md            <- cách phát triển: quy trình + gate (v1.2.4 tách AGENT_PROTOCOL.md + VALIDATION_SPEC.md)
    EVIDENCE.md               <- chỉ mục bằng chứng (bắt buộc)
    evidence/                 <- log/hash/verdict thô
    work-packages/            <- work-package + evidence con
```

## Map version hiện có

| Thư mục | Trạng thái | Tài liệu chính |
|---|---|---|
| `docs/v1.1.0/` | Release cũ (historical) | MASTER_PLAN, INTERFACE_CONTRACT, SPEC_TRACEABILITY, benchmarks |
| `docs/v1.2.0/` | Release cũ (historical) | SPEC-AMENDMENT-001 (canonical truth), decisions/ADR-009, work-packages |
| `docs/v1.2.2/` | Historical | agent-development-system, audit, decisions, handoff, work-packages |
| `docs/v1.2.3/` | Historical | README, BASELINE-AUDIT, RELEASE-NOTES, evidence, work-packages |
| `docs/v1.2.4/` | **Version active (đã release)** | README, MASTER_PLAN, ARCHITECTURE, TECH_STACK, VALIDATION_SPEC, AGENT_PROTOCOL, evidence, work-packages |
| `docs/v1.3.0/` | Chưa tồn tại | Tạo từ `docs/VERSION-TEMPLATE.md` khi bắt đầu |

## Bằng chứng phát triển gần đây (P1 — retrieval quality)

Các work-package và handoff đã thực hiện trên nhánh `v124-post-release-closure`
(commit `f32d18d` → `e016172`), bằng chứng thật tại `zero-mem-dev-data/evidence/`:

| Work | Kết quả | Handoff |
|---|---|---|
| Benchmark memory recall/token (29 gold queries) | recall@8 0.625, stale-safe 1.0, isolation OK, determinism True | `artifacts/handoffs/P1-BENCHMARK-HANDOFF.md` |
| FTS hyphen normalization | `walk-forward` → hit; full suite 3375→3378 xanh | `artifacts/handoffs/P1-HYPHEN-FIX-HANDOFF.md` |
| Option B — state priority trong PROJECT EvidenceSet | B01/B03/B06/B09/B10 hit state; recall@8 0.625 | `artifacts/handoffs/P1-ORDERING-HANDOFF.md` |
| Scale harness N=500 | 485 events, 52 queries, recall@8 0.519, p95 2.09ms | `benchmarks/scale_memory_benchmark.py` + `zero-mem-dev-data/evidence/p1-scale500/` |

> Lưu ý trung thực: các con số trên là **baseline functional** trên corpus tổng hợp nhỏ;
> chưa phải gate release. Chờ work-package scale/đánh giá tiếp theo trước v1.3.

## Quy ước khi tạo version mới

1. Tạo `docs/vX.Y.Z/` bằng cách copy khung trong `docs/VERSION-TEMPLATE.md`.
2. Điền đầy đủ các file bắt buộc (README, ROADMAP, ARCHITECTURE, TECH_STACK, DEVELOPMENT, EVIDENCE) **trước khi code**.
3. Mỗi work-package phải có evidence con trong `docs/vX.Y.Z/work-packages/<id>/evidence/` (manifest/log/hash/verdict).
4. Kết thúc version: `EVIDENCE.md` phải liệt kê đủ bằng chứng + status; không tuyên bố release khi thiếu gate.
5. **Không sửa file trong version đã đóng** (v1.1.0–v1.2.4 sau release) trừ khi là supersede có ghi chú rõ.

## Tài liệu xuyên version

- `docs/architecture/ARCHITECTURE.md` — kiến trúc tổng thể (M0+), nguồn quyền lực tham chiếu `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
- `docs/governance/GITHUB-POLICY.md` — bắt buộc đọc trước mọi thao tác Git/GitHub.
- `docs/acceptance/` — acceptance M0..M10 (evidence chính của milestone).
- `docs/audits/` — audit tổng hợp (post-m10, packaging).
