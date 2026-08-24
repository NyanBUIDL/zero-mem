# v1.4.1 — Checklist thực thi

> Hai tầng: **CHECKLIST GỐC** áp dụng 100% cho mọi WP; **CHECKLIST RIÊNG** đo mục tiêu đặc thù
> từng WP. Tick chỉ khi có evidence vật lý (lệnh + output nguyên văn).

---

## CHECKLIST GỐC (mọi WP, không ngoại lệ)

```
[ ] SCOUT report hoàn tất TRƯỚC khi Builder gõ phím (nếu WP đụng code)
[ ] Scope chốt bằng văn bản: file được sửa / file cấm đụng
[ ] Registry entry tồn tại TRƯỚC code (mọi defect)
[ ] RED-first test nếu đụng product src/ hoặc zero_mem/
[ ] Focused test PASS + evidence nguyên văn (lệnh + output)
[ ] Full suite PASS (isolated HOME, venv Py 3.13)
[ ] Self-review: architecture / canonical-vs-derived / provenance /
    token-storage cost / failure path
[ ] VERIFIER độc lập (subagent tách session) xác nhận — verdict nguyên văn
[ ] Handoff Markdown theo template (Observed/Changed/Verified/Risk/Next/Authorization)
[ ] project-state.yaml overlay cập nhật (V141-Rx_status) — chỉ ở R4 trừ khi WP riêng lẻ đóng
[ ] Commit tham chiếu đúng ID (V141-Rx / DEF-xxx)
```

---

## V141-R0 — Registry + phạm vi

```
[ ] SCOUT: xác minh lại từng phát hiện trên cây hiện hành (không tin báo cáo cũ):
    - grant CLI store tách biệt đường ủy quyền production (truy vết call-path)
    - connection leak (_resolve_space_or_none finally:pass; close() thiếu corpus_conn)
    - dead code run_grant_list; assert production; sqlite3_error() hack
    - doctor PASS không verify path lúc chạy
[ ] Đăng ký DEF-013: grant CLI không nối control-plane thật + nguồn sự thật kép cho grants
[ ] Đăng ký DEF-014: connection lifecycle (corpus_conn leak ×2 điểm)
[ ] Đăng ký DEF-015: hygiene bundle CLI (dead code / naming / assert / doctor check)
[ ] Đăng ký DEF-016: verification gap — acceptance test không đi qua _open_facade thật;
    evidence lệch số (claim 3515/6 vs tái lập 3514/7) cần chốt số chính thức
[ ] Trình GATE-R0: duyệt registry + ROADMAP.md + checklist này
```

## V141-R1 — ADR grant CLI (A/B)

```
[ ] SCOUT impact-set (Graphify read-only, disposable): call-path của grant CLI hiện tại,
    và của phương án B (CLI → control-plane data-root của sidecar runtime)
[ ] ADR draft docs/v1.4.1/ADR-V141-01-GRANT-CLI.md:
    - Phương án A: revert phần CLI khỏi v1.4.1 (giữ core fix DEF-012); chi phí, rủi ro,
      những gì mất đi (tiện ích admin thủ công)
    - Phương án B: wire CLI vào đúng data-root control-plane; thiết kế canonical event log
      chung; lifecycle khi runtime đang chạy; migration implications
    - Khuyến nghị + lý do theo tiêu chí Decision Style của dự án
[ ] GATE-R1: maintainer chọn A/B
```

## V141-R2 — Implement theo lựa chọn R1 + DEF-014 + DEF-015

```
[ ] RED-first test cho DEF-013 fix (theo A/B đã chọn) — chạy FAIL trước khi sửa
[ ] Smallest change cho DEF-013; KHÔNG mở rộng phạm vi ngoài ADR
[ ] RED-first DEF-014: test chứng minh leak (conn đếm được / mock close) rồi fix lifecycle
[ ] DEF-015 hygiene: mỗi mục 1 thay đổi nhỏ nhất, có test/regression tương ứng
[ ] Focused tests PASS + verbatim evidence
[ ] Full suite PASS (baseline mới: ≥3514 passed, 0 failed, isolated HOME)
[ ] Self-review + Verifier độc lập PASS
```

## V141-R3 — Verification gap closure

```
[ ] Test chấp nhận MỚI gọi handler path thật: _open_facade với runtime env-configured +
    corpus store hợp lệ → space grant authorizing event read end-to-end
[ ] Test cũ giữ lại làm unit-level pin (KHÔNG xoá test để pass — Test Integrity)
[ ] Tái lập full suite ≥2 lần liên tiếp, cùng con số → chốt số evidence chính thức ghi
    registry + state overlay
```

## V141-R4 — Closure & release readiness

```
[ ] Version bump 1.4.1 theo checklist DEF-006: zero_mem/version.py + release_common.py:127
    + test_pkg1/pkg2/pkg6 pins (grep toàn bộ "1.4.0")
[ ] Packaging tests PASS sau bump
[ ] project-state.yaml: V141 overlay đầy đủ (status, scope, per-WP status, final suite,
    defect refs) — đúng định dạng các overlay V133/V134/V140
[ ] EVIDENCE.md v1.4.1 + RELEASE-NOTES-v1.4.1.md (kê khai rõ: hotfix DEF-012 wiring +
    remediation DEF-013..016; KHÔNG oversell grant CLI nếu chọn A)
[ ] DEFECT-REGISTRY: đóng DEF-012 (đã), DEF-013..016 với evidence verbatim
[ ] Full suite cuối cùng PASS trên tree cuối
[ ] GATE-FINAL-V141 draft → duyệt → tag v1.4.1 local (push là mutation riêng, cần chỉ thị)
```

---

## Stop rules bất biến (nhắc lại từ ROADMAP)

- Cùng lỗi lặp ≥3 lần → DỪNG hỏi.
- Defect mới phát hiện trong quá trình fix → đăng ký registry TRƯỚC, không sửa liền.
- Gate chưa duyệt → không sang WP kế.
- KHÔNG push/tag trước GATE-FINAL-V141.
