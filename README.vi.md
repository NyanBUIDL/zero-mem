# Zero-Mem

[English](README.md) · [Tiếng Việt](README.vi.md)

Zero-Mem là sidecar bộ nhớ và bằng chứng theo hướng local-first dành cho quy
trình agent. Hệ thống ghi nhận event canonical bền vững, tạo các projection có
thể tái dựng để truy vấn, áp dụng ranh giới truy cập rõ ràng và tách vòng đời dữ
liệu người dùng khỏi vòng đời cài đặt ứng dụng.

Core runtime không có dependency bên thứ ba bắt buộc, không cần AI API và không
cần kết nối mạng để vận hành thông thường.

## Trạng thái dự án

| Dòng phát triển | Trạng thái | Ghi chú |
|---|---|---|
| Package `1.6.0` | Phiên bản package phát hành hiện tại | Được khai báo tại `zero_mem/version.py` |
| `master` | Branch ổn định mới nhất | Dòng tích hợp ổn định |
| `v160/multi-ks` | Source release đã qualification | C1–C10 + wizard hoàn tất; remote 9-cell CI đã xanh |

v1.6.0 đã hoàn tất qualification cục bộ và remote. Publication được xác định
bằng tag bất biến `v1.6.0` và GitHub Release.

Xem [hướng dẫn v1.6.0](docs/v1.6.0/README.md) để biết phạm vi, gate, bản đồ
work-package và chỉ mục evidence chính thức.

## Nguyên tắc cốt lõi

- **Local-first:** hoạt động thông thường diễn ra cục bộ và offline.
- **Lịch sử canonical:** Memory JSONL là nguồn sự thật append-only cho event và trace.
- **Projection có thể tái dựng:** SQLite, FTS, graph, temporal index và projection
  kiểu Obsidian đều là derived state.
- **Danh tính tường minh:** project, profile và Knowledge Space không được suy ra
  từ working directory, tên repository, branch, HOME hoặc nội dung phiên làm việc.
- **Phân quyền trước truy xuất:** các đường đọc theo scope phải fail-closed và giữ
  đúng ranh giới profile/project/Knowledge Space.
- **Vòng đời không phá huỷ:** upgrade và uninstall không được âm thầm xóa hoặc
  viết lại dữ liệu canonical của người dùng.
- **Phát triển dựa trên bằng chứng:** thay đổi phải RED-first, commit có phạm vi
  nhỏ và có qualification evidence thực thi được.

## Khả năng chính

Zero-Mem cung cấp:

- capture event bền vững với receipt tường minh;
- lưu trữ canonical JSONL và SQLite projection có thể rebuild;
- truy xuất có cấu trúc và full-text search;
- kiểm soát truy cập theo profile, project và Knowledge Space;
- các lớp project-memory, graph, temporal, corpus và projection;
- public Python facade và CLI cục bộ;
- tích hợp Hermes tùy chọn qua boundary tường minh;
- backup, restore, chẩn đoán và upgrade cục bộ có kiểm chứng;
- công cụ import corpus tổng quát cho bộ tài liệu của người dùng.

Corpus tooling không bị khóa vào sample `quant_lab` dùng khi phát triển. Các
lệnh import và projection được tham số hóa để những domain khác có thể dùng
cùng pipeline.

## Bản đồ repository

```text
zero_mem/        Public Python API, CLI, cấu hình và lệnh quản lý vòng đời
src/             Implementation nội bộ, chia theo domain
tests/           Unit, integration, packaging, fixture và baseline
docs/            Kiến trúc, kế hoạch, quyết định, runbook, release và evidence
artifacts/       Control, handoff, tracking và evidence lịch sử
audit/           Artifact audit/qualification thô chưa được hợp nhất
benchmarks/      Harness hiệu năng và chất lượng truy xuất
config/          Policy và schema mẫu
examples/        Ví dụ tích hợp nhỏ
release_helpers/ Công cụ bundle, cài đặt và gỡ cài đặt offline
scripts/         Công cụ verification, corpus, bảo trì và projection
```

Việc tách hai cây Python là có chủ đích:

- `zero_mem/` là bề mặt public và vận hành được hỗ trợ;
- `src/` chứa implementation nội bộ theo domain.

Đọc [module map hiện hành](docs/v1.6.0/MODULE-MAP.md) trước khi thêm module mới.

Các file quản trị ở root có vai trò khác nhau:

- `project-state.yaml` là trạng thái máy hiện hành và là nơi duy nhất trong nhóm
  này được bổ sung status overlay mới.
- `implementation-plan.json` là lịch sử đã đóng băng; không cập nhật tiếp.
- `benchmark-plan.json` là hợp đồng benchmark M0 ban đầu, không phải trạng thái
  release hay kết quả benchmark hiện tại.
- `Review V1.1/` là tài liệu review lịch sử được giữ lại để audit.

Để tìm tài liệu, bắt đầu tại [chỉ mục tài liệu](docs/README.md). Để hiểu authority
và invariant của repository, đọc [AGENTS.md](AGENTS.md).

## Khởi động nhanh cho phát triển

Yêu cầu: Python 3.11–3.13.

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m pytest -q
```

Kiểm tra CLI mà không thay đổi dữ liệu người dùng:

```bash
zero-mem --help
zero-mem --version
zero-mem version
```

PDF extra tùy chọn sử dụng `pypdf`:

```bash
python -m pip install -e ".[pdf]"
```

## Onboarding có hướng dẫn (khuyến nghị)

Sau khi cài wheel Zero-Mem, cách khởi động an toàn và ngắn nhất là:

```bash
zero-mem wizard
```

Wizard sẽ khởi tạo storage cục bộ, cho phép cấu hình Hermes nếu muốn, rồi chạy
health check chỉ đọc. Nếu tìm thấy Hermes, wizard giải thích và yêu cầu hai ID
tường minh; Zero-Mem không tự đoán identity và không đọc secret của Hermes.

- **Project ID** là định danh ổn định của codebase/workspace trong Hermes, không
  phải đường dẫn thư mục.
- **Profile ID** là định danh profile hành vi/quyền truy cập đang dùng trong
  Hermes, không phải username của hệ điều hành.

Nếu chưa biết hai giá trị này, hãy bỏ qua Hermes và cấu hình sau. Với automation:

```bash
zero-mem wizard --non-interactive --skip-hermes --json
zero-mem wizard --non-interactive --project-id PROJECT --profile-id PROFILE --json
```

Xem [hướng dẫn onboarding đầy đủ](docs/v1.6.0/ONBOARDING.md).

## Khởi tạo cục bộ thủ công và kiểm tra sức khỏe

```bash
zero-mem setup
zero-mem doctor
zero-mem doctor --json
```

`setup` tạo các thư mục data, config, state và cache riêng tư của người dùng,
một Memory JSONL canonical rỗng và SQLite schema dẫn xuất. Lệnh này không yêu
cầu Hermes, Corpus, Obsidian, AI API, kết nối mạng hoặc checkout repository.

`doctor` chỉ đọc. Những integration tùy chọn chưa có sẽ được báo là optional
hoặc warning, không bị coi là lỗi setup.

## Tích hợp Hermes tùy chọn

```bash
zero-mem integrate hermes --check
zero-mem integrate hermes --project-id PROJECT --profile-id PROFILE
zero-mem integrate hermes --remove
```

`setup`, `doctor` và startup không tự động bật integration. Project ID và
profile ID là bắt buộc. Zero-Mem chỉ lưu descriptor do mình sở hữu, không sửa
hoặc cài đặt Hermes. `ZERO_MEM_ENABLED` vẫn là công tắc chính; Hermes phải tiếp
tục vận hành khi Zero-Mem không khả dụng.

## Backup và upgrade

```bash
zero-mem backup create --output /absolute/backup-directory
zero-mem backup verify /absolute/backup-directory --json
zero-mem backup restore /absolute/backup-directory --yes

zero-mem upgrade --check --json
zero-mem upgrade --json
```

`upgrade --check` chỉ đọc. `upgrade` kiểm tra dữ liệu canonical, rebuild derived
state trong staging và chỉ kích hoạt sau khi xác minh thành công. Nếu staging
thất bại, derived state đang hoạt động trước đó vẫn được giữ nguyên. Schema từ
tương lai sẽ bị từ chối thay vì bị âm thầm downgrade.

Gỡ ứng dụng không đồng nghĩa với xóa dữ liệu. Uninstaller mặc định giữ lại
Memory JSONL canonical, corpus registry và blob, artifact, profile/grant, cấu
hình và backup.

## Các điểm vào tài liệu

- [Chỉ mục tài liệu](docs/README.md)
- [Quy tắc có thẩm quyền của repository](AGENTS.md)
- [Bản chiếu master specification](docs/MASTER-SPEC.md)
- [Kiến trúc](docs/architecture/ARCHITECTURE.md)
- [Defect registry](docs/defects/DEFECT-REGISTRY.md)
- [Release notes](docs/releases/)
- [Hướng dẫn Multi-KS v1.6.0](docs/v1.6.0/README.md)
- [Quyết định kiến trúc v1.6.0](docs/v1.6.0/decisions/ADR-V160-01-MULTI-KS.md)
- [Roadmap v1.6.0](docs/v1.6.0/ROADMAP.md)
- [Chỉ mục evidence v1.6.0](docs/v1.6.0/EVIDENCE.md)

## Đóng góp an toàn

Trước khi sửa code, đọc [AGENTS.md](AGENTS.md), kế hoạch version, ADR liên quan
và defect registry. Trước mọi thao tác thay đổi Git hoặc GitHub, đọc
[GitHub governance policy](docs/governance/GITHUB-POLICY.md).

Không rewrite canonical history, làm yếu ranh giới truy cập, coi derived state
là canonical, commit dữ liệu sinh ra/dữ liệu riêng tư hoặc tuyên bố hoàn thành
khi chưa có bằng chứng thực thi.
