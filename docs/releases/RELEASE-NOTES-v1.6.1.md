# RELEASE NOTES — Zero-Mem v1.6.1

**Trạng thái:** ADDITIVE PATCH CANDIDATE — chỉ publish sau khi exact release
commit đạt local qualification, remote 9-cell qualification và SHA invariant.

## Phạm vi

v1.6.1 là bản vá hậu kiểm tối thiểu trên v1.6.0. Bản này không đổi schema,
canonical event format, authorization semantics, retrieval behavior hay public
product API.

- Thêm MIT `LICENSE` với chủ thể `NyanBUIDL` và đưa `LICENSE` vào wheel/sdist.
- Thêm `NOTICE` ghi attribution bài báo gốc, ranh giới MIT/CC BY-NC-SA và tuyên
  bố đây không phải implementation chính thức của nhóm tác giả.
- Đồng bộ package author metadata thành `NyanBUIDL`.
- Sửa PKG-1 wheel acceptance dùng version của artifact thay vì hardcode `1.2.2`,
  đồng thời hỗ trợ layout `Scripts` và console `.exe` trên Windows.
- Sửa PKG-2 test environment dùng temp root ngắn trên Windows nhưng vẫn kiểm tra
  path có khoảng trắng; subprocess failure giờ giữ bounded inner stderr.
- Sửa hai false failure của remote qualification: PKG-1 dùng path containment
  thay vì substring; PKG-2 resolve platform temp alias trước security check.
- Nâng action pins của workflow v1.6.1 lên dòng v7 để bỏ runtime Node 20 đã
  deprecated; permissions của workflow vẫn chỉ `contents: read`.
- Sửa release notes v1.6.0 phản ánh publication đã hoàn tất và cấm dùng artifact
  build từ post-tag working tree để thay artifact v1.6.0.
- Thêm tài liệu `SECURITY.md` và `CONTRIBUTING.md` tối thiểu.

## Research provenance

Zero-Mem là dự án kỹ thuật độc lập được định hướng bởi Xiao và cộng sự,
"Zero-Mem: Zero-Token Memory Operations for LLM Agents," arXiv:2607.29377
(2026). MIT của repository không tái cấp phép nội dung bài báo, hình, bảng,
dataset hoặc code do nhóm tác giả có thể công bố sau này. Xem `NOTICE`.

## Tương thích và rollback

- Không migration; dữ liệu canonical và derived schema giữ nguyên v13.
- Có thể rollback code/docs của patch bằng additive revert; không di chuyển hay
  thay thế tag/artifact v1.6.0.
- Runtime root tùy chỉnh quá dài trên Windows chưa bật long-path vẫn có thể làm
  CPython `venv/ensurepip` thất bại; installer giờ trả lại chi tiết nguyên nhân.
- Host dùng Windows Application Control có thể chặn console executable vừa tạo
  trong venv (`WinError 4551`); đây là host-policy denial và phải được giải quyết
  hoặc retry xác minh trên môi trường được phép, không được coi là wheel failure.

## Qualification

Evidence cục bộ và remote được ghi tại `docs/v1.6.1/EVIDENCE.md`. Artifact chỉ
được publish nếu build từ exact tagged commit và có version `1.6.1`.
