# Zero-Mem

## Bộ nhớ ngoài cục bộ, có thể kiểm chứng cho AI agent

Zero-Mem giúp AI agent lưu lại và truy xuất những dấu vết công việc quan trọng giữa các phiên làm việc. Thay vì chỉ dựa vào lịch sử chat ngắn hạn hoặc “trí nhớ” do mô hình tự báo cáo, Zero-Mem hướng tới dữ liệu có nguồn gốc, trạng thái xác minh và quyền truy cập rõ ràng.

Hermes là một lớp tích hợp tùy chọn, không phải lõi của dự án. Mục tiêu là để Zero-Mem có thể phục vụ Hermes, agent khác hoặc ứng dụng cục bộ mà không gắn chặt vào một framework duy nhất.

> **Trạng thái:** nền tảng phát hành là **v1.0.0**. Dự án đang lập kế hoạch **v1.1.0**, chưa phải bản đã hoàn thiện để cài đặt/vận hành. Phần lộ trình dưới đây mô tả mục tiêu đang được rà soát, không phải danh sách tính năng đã phát hành.

## Tải dự án

### Cách 1: Dùng Git

```powershell
git clone https://github.com/NyanBUIDL/zero-mem.git
Set-Location zero-mem
```

Để xem đúng nền tảng v1.0.0:

```powershell
git checkout v1.0.0
```

Để xem nhánh tài liệu v1.1.0:

```powershell
git checkout codex/v1.1-planning
```

### Cách 2: Tải ZIP

Mở [NyanBUIDL/zero-mem trên GitHub](https://github.com/NyanBUIDL/zero-mem), chọn **Code → Download ZIP**, sau đó giải nén tệp vào thư mục làm việc.

## Sử dụng bằng Terminal

Zero-Mem là một sidecar bộ nhớ và bằng chứng theo định hướng local-first. Các gói PKG-1 đến PKG-6 của nền tảng v1.0.0 cung cấp gói cài đặt, CLI và các luồng vận hành cục bộ dưới đây.

### Kiểm tra CLI và phiên bản

Sau khi cài đặt, dùng các lệnh sau để kiểm tra CLI và phiên bản:

```bash
zero-mem --help
zero-mem --version
zero-mem version
```

Core runtime không bắt buộc thư viện bên thứ ba. Nếu cần trích xuất nội dung PDF, cài thêm extra `pdf` để dùng `pypdf`.

### Cài đặt từ acceptance bundle

PKG-2 cung cấp công cụ tạo acceptance bundle ngoại tuyến tại `packaging/build_bundle.py`, cùng `install.sh` và `uninstall.sh`.

- Installer chỉ nhận wheel nằm trong bundle, không tải thêm từ mạng sau khi bundle đã có.
- Installer tạo runtime được quản lý theo phiên bản tại `${XDG_DATA_HOME:-$HOME/.local/share}/zero-mem`.
- CLI được đặt tại `${XDG_BIN_HOME:-$HOME/.local/bin}/zero-mem`.
- Không cần quyền `root` và không cần mạng sau khi nhận bundle.
- Gỡ cài đặt mặc định chỉ xóa runtime và CLI shim do Zero-Mem sở hữu, luôn giữ lại dữ liệu người dùng.

### Khởi tạo và chẩn đoán cục bộ

PKG-3 thêm các lệnh khởi tạo không phá hủy dữ liệu:

```bash
zero-mem setup
zero-mem doctor
zero-mem doctor --json
```

`setup` tạo các thư mục dữ liệu, cấu hình, trạng thái và cache riêng tư theo XDG; một stream Memory JSONL chuẩn trống; và schema SQLite dẫn xuất. Lệnh kết thúc với trạng thái `READY`.

Lần khởi tạo đầu tiên không yêu cầu Hermes, Corpus, Obsidian, AI API, mạng hoặc một repository checkout. `doctor` là lệnh chỉ đọc, trả về các kiểm tra ổn định `PASS`, `WARN`, `OPTIONAL` hoặc `FAIL`; thiếu tích hợp tùy chọn chỉ là cảnh báo/khả năng tùy chọn, không làm `setup` thất bại.

### Tích hợp Hermes (tùy chọn)

PKG-4 cung cấp quy trình tích hợp Hermes rõ ràng và hoàn toàn tùy chọn:

```bash
zero-mem integrate hermes --check
zero-mem integrate hermes --project-id PROJECT --profile-id PROFILE
zero-mem integrate hermes --remove
```

- `setup`, `doctor` và khởi động thông thường không tự bật tích hợp Hermes.
- `PROJECT` và `PROFILE` là bắt buộc; Zero-Mem không suy luận chúng từ thư mục hiện tại, tên repository, `HOME`, nội dung phiên hoặc nhánh Git.
- Lệnh chỉ lưu descriptor thuộc sở hữu Zero-Mem tại XDG config root đã cấu hình; không sửa file Hermes, không cài Hermes và không liên hệ mạng.
- Tích hợp không mở công cụ ghi, quản trị hay raw-storage.
- `ZERO_MEM_ENABLED` là công tắc chủ duy nhất. Hermes vẫn hoạt động khi Zero-Mem không khả dụng.

### Nâng cấp và vòng đời dữ liệu

Mã ứng dụng và dữ liệu người dùng có vòng đời riêng. Cài lại hoặc gỡ runtime được quản lý không xóa Memory JSONL chuẩn, corpus registry/blobs chuẩn, artifact, profile/grant, cấu hình hoặc backup.

PKG-6 cung cấp luồng nâng cấp cục bộ, không dùng mạng:

```bash
zero-mem upgrade --check --json
zero-mem upgrade --json
```

`upgrade --check` là chỉ đọc. Lệnh báo cáo tính tương thích của package, định dạng dữ liệu và SQLite schema; khả năng đọc dữ liệu chuẩn; tình trạng sẵn sàng backup; và kết quả doctor. Zero-Mem từ chối derived schema ở tương lai và không âm thầm hạ cấp dữ liệu. Với schema v10 tương thích, kết quả là `NO_MIGRATION_REQUIRED`.

`upgrade` xác thực dữ liệu chuẩn, dựng lại trạng thái SQLite/FTS/graph/temporal có thể bỏ đi trong thư mục staging cùng cấp, rồi chỉ kích hoạt sau khi rebuild và doctor thành công. Memory JSONL chuẩn, corpus registry/blobs, artifact payload, profile/grant và cấu hình không bị migrate hay ghi lại. Nếu staging thất bại, derived state đang hoạt động vẫn được giữ nguyên.

Trước một đợt nâng cấp quan trọng, hãy tạo và xác minh backup PKG-5 cục bộ:

```bash
zero-mem backup create --output /absolute/backup-directory
zero-mem backup verify /absolute/backup-directory --json
```

PKG-6 chủ ý không có lệnh `zero-mem data remove`. Xóa dữ liệu bền vững là thao tác vòng đời riêng cần được ủy quyền rõ ràng; gỡ OS package không có nghĩa là xóa dữ liệu.

## Zero-Mem dùng để làm gì?

- **Ghi nhớ công việc dài hạn:** lưu trace của tác vụ, quyết định và bối cảnh để agent có thể tiếp tục công việc ở phiên sau.
- **Tìm đúng thông tin cần thiết:** truy xuất theo nội dung, thời gian, dự án hoặc quan hệ; kết quả bị giới hạn để không đưa quá nhiều ngữ cảnh vào agent.
- **Bảo vệ dữ liệu theo quyền:** hệ thống xác định quyền trước khi một trace có thể ảnh hưởng đến tìm kiếm, xếp hạng, ngữ cảnh hoặc bản chiếu.
- **Kiểm chứng được:** provenance, xung đột và độ không chắc chắn cần được giữ lại; trạng thái đã xác minh luôn quan trọng hơn lời tự báo cáo của agent.
- **Làm việc cục bộ:** các thao tác bộ nhớ thông thường hướng đến cơ chế xác định được, không yêu cầu bắt buộc gọi LLM hay dịch vụ mạng bên ngoài.
- **Làm việc cùng Obsidian có kiểm soát:** Obsidian là không gian tri thức dành cho con người; mọi chỉnh sửa cần review trước khi trở thành dữ liệu chuẩn.

## Nguyên tắc dữ liệu và an toàn

```text
Agent / Hermes / ứng dụng cục bộ
              │
              v
       Giao diện Zero-Mem
              │
              v
Lọc bí mật → kiểm tra quyền → lưu trace có provenance
              │
              v
 JSONL append-first + metadata vòng đời SQLite
              │
              v
  Chỉ mục, đồ thị và Obsidian có thể dựng lại
```

- Bí mật phải được che hoặc từ chối trước mọi điểm lưu trữ.
- Dữ liệu chuẩn được ghi theo hướng append-first để có lịch sử và khả năng phát lại.
- Chỉ mục FTS, đồ thị và bản chiếu Obsidian là thành phần có thể dựng lại, không thay thế nguồn dữ liệu chuẩn.
- Các chế độ cô lập hoặc giới hạn nguồn không được rò rỉ nội dung, định danh, số lượng, điểm số hay dấu hiệu phụ.
- Hermes phải luôn là adapter tùy chọn; Zero-Mem core không phụ thuộc mã Hermes.

## Lộ trình v1.1.0

v1.1.0 hướng tới một sidecar bộ nhớ cục bộ, độc lập agent, với dữ liệu truy nguyên được và giao diện công khai ổn định.

1. **Đối chiếu nền tảng:** xác nhận v1.0.0, `master`, các phát hiện F-001–F-014 và quy tắc phê duyệt.
2. **Kiến trúc, cấu hình và dữ liệu chuẩn:** hoàn thiện ranh giới core, hợp đồng cấu hình, JSONL/SQLite, freshness, retention, replay và rebuild.
3. **Truy xuất và knowledge space:** truy xuất có quyền, profile, scope, xếp hạng xác định được và ngân sách ngữ cảnh.
4. **Giao diện agent cục bộ:** chuẩn hóa `zero_mem.search`, `zero_mem.get_trace`, `zero_mem.get_task_state` và `zero_mem.get_decisions`; sau đó đưa vào sidecar/MCP cục bộ an toàn.
5. **Tích hợp và vận hành:** Hermes adapter tùy chọn, migration/rollback, đóng gói, quan sát, xử lý xung đột và tương thích ngược.
6. **Obsidian có review/write-back:** Vault quản lý, provenance, đồng bộ bản chiếu và ghi lại dữ liệu chuẩn chỉ sau khi được duyệt.
7. **Kiểm thử và phát hành:** kiểm thử quyền riêng tư, hiệu năng, migration và conformance trước quyết định phát hành.

Xem lộ trình, dependency và tiêu chí phát hành đầy đủ tại [Kế hoạch v1.1.0](docs/v1.1.0/MASTER_PLAN.md). Bản mô tả chi tiết bằng tiếng Việt nằm trong [tài liệu v1.1.0](docs/README.md).

## Tài liệu

- [Tổng quan v1.1.0 bằng tiếng Việt](docs/README.md)
- [Trạng thái hiện tại](docs/v1.1.0/STATUS.md)
- [Baseline v1.0.0](docs/baseline/V1.0.0_BASELINE.md)
- [Các phát hiện và đối chiếu](docs/audit/FINDINGS_INDEX.md)
- [Quy tắc đóng góp và phạm vi thay đổi](AGENTS.md)
