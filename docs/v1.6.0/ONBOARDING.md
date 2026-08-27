# Wizard và onboarding Zero-Mem

## Cách dùng khuyến nghị

Sau khi cài Zero-Mem từ wheel, chạy:

```bash
zero-mem wizard
```

Wizard thực hiện ba bước theo thứ tự: kiểm tra lựa chọn trước khi ghi dữ liệu,
khởi tạo storage cục bộ idempotent, rồi chạy `doctor`. Hermes luôn là tùy chọn.

## Project ID và Profile ID

- **Project ID** là định danh ổn định mà Hermes dùng cho codebase/workspace hiện
  tại. Đây là ID logic, không phải đường dẫn repository và không phải toàn bộ
  source tree.
- **Profile ID** là định danh profile Hermes đang điều khiển behavior và access
  scope. Đây không phải username Windows/macOS/Linux.

Sao chép hai ID từ cấu hình project/profile hiện hành của Hermes. Zero-Mem không
đọc secret, không quét `~/.hermes`, không suy luận ID từ cwd/repository và không
tự cài hoặc sửa Hermes. Nếu chưa chắc ID nào đúng, chọn bỏ qua và cấu hình sau:

```bash
zero-mem integrate hermes --project-id PROJECT --profile-id PROFILE
```

## Chế độ standalone

Không cần Hermes để dùng core Zero-Mem:

```bash
zero-mem wizard --non-interactive --skip-hermes --json
```

Lệnh tạo cấu hình, canonical JSONL và derived SQLite thuộc Zero-Mem, sau đó trả
report JSON ổn định. `--skip-hermes` không xóa integration đã tồn tại.

## Chế độ Hermes không tương tác

```bash
zero-mem wizard \
  --non-interactive \
  --project-id PROJECT \
  --profile-id PROFILE \
  --json
```

Hai ID phải đi cùng nhau. `--skip-hermes` không được kết hợp với ID. JSON chỉ
chứa trạng thái bounded, không echo ID hoặc đường dẫn riêng tư.

## Chạy lại và xử lý lỗi

Wizard có thể chạy lại: setup là idempotent và integration hợp lệ hiện có được
giữ nguyên nếu người dùng không yêu cầu thay thế bằng cặp ID tường minh. Request
không hợp lệ bị từ chối trước mutation. Nếu wizard báo `NOT_READY`, chạy:

```bash
zero-mem doctor
zero-mem integrate hermes --check
```

Muốn quay về standalone, chỉ xóa descriptor do Zero-Mem sở hữu bằng:

```bash
zero-mem integrate hermes --remove
```

Lệnh này không gỡ Hermes và không xóa canonical memory.
