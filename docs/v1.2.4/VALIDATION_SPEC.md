# Validation Specification v1.2.4

## Gate hierarchy

| Gate | Required checks | Blocking condition |
|---|---|---|
| G0 Contract | Schema, modes, ownership, failure semantics reviewed | Ambiguous public behavior |
| G1 Unit | Mapping, IDs, bounds, redaction, state transitions | Any required failure |
| G2 Integration | Hermes → capture → projection → authorized read | Broken/parallel composition |
| G3 Failure/security | Deny-before-read, secret rejection, restart, corruption, saturation | Leakage or false success |
| G4 Platform | Windows/Linux/macOS, Python 3.11–3.13 | Core path skip/failure |
| G5 Packaging | Wheel/sdist clean install and CLI/Hermes smoke | Artifact differs from source SHA |
| G6 Release | Full evidence manifest + independent audit | Missing evidence/open blocker |

## Runtime-mode truth table

| Assertion | off | observe | assist | inject |
|---|---:|---:|---:|---:|
| Writer opened | No | Yes | Yes | Yes |
| Conversation captured | No | Yes | Yes | Yes |
| Read tool registered | No | No | Yes | Yes |
| Injection hook registered | No | No | No | Yes |
| Health reports exact mode | Yes | Yes | Yes | Yes |

Mỗi ô phải có test trực tiếp; không suy ra từ một biến `enabled`.

## Semantic capture acceptance

- Hai message khác nhau không có host event ID không được deduplicate nhầm.
- Retry có cùng session/task/turn/role phải ổn định identity.
- User/assistant/tool/skill/subagent có semantic event/source đúng.
- Host payload không bị mutate; callback result/exception không đổi.
- Raw secret và duplicated conversation history không vào canonical event.

## Storage/freshness acceptance

- Canonical append success tồn tại sau projection failure/restart.
- `last_projected_sequence <= last_canonical_sequence`.
- `CURRENT` chỉ khi watermark bằng nhau và identity/checkpoint hợp lệ.
- `STALE` thể hiện lag; `UNAVAILABLE` thể hiện derived không dùng được.
- Capture/read/injection/health phải báo cùng storage identity.
- Recovery không mutate JSONL và không promote file sai identity.

## Authorized read and HITL acceptance

- Denial diễn ra trước SQL/FTS discovery và không rò count/ID/snippet/timing detail.
- `EMPTY`, `STALE`, `DENIED`, `UNAVAILABLE` giữ nguyên ý nghĩa tới Hermes.
- Correction tạo linked event; original trace vẫn tồn tại.
- Delete-request không xóa canonical record; projection áp tombstone có provenance.
- Agent-generated Skill chỉ được active sau schema/security/test/review gate; Zero-Mem không tự ghi đè `SKILL.md`.

## Cross-platform matrix

| OS | Python | Core storage | Hermes E2E | Packaging | Required |
|---|---|---:|---:|---:|---:|
| Windows | 3.11, 3.12, 3.13 | Pass | Pass | Pass | Yes |
| Ubuntu Linux | 3.11, 3.12, 3.13 | Pass | Pass | Pass | Yes |
| macOS | 3.11, 3.12, 3.13 | Pass | Pass | Pass | Yes |

Không dùng symlink privilege của máy dev làm lý do tuyên bố pass. Test phải skip có điều kiện với reason rõ ràng hoặc dùng CI environment phù hợp; core acceptance vẫn cần một job thực thi thật.

## Evidence format

```text
docs/v1.2.4/evidence/<tested-full-sha>/<gate>/
  manifest.json
  manifest.md
  commands.txt
  environment.txt
  logs/
  hashes/SHA256SUMS.txt
```

Manifest phải phân biệt `pass`, `fail`, `skip`, `error`; thiếu log/checksum/SHA là gate failure.

