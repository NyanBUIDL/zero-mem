# Work Package Template v1.2.4

Sao chép nội dung dưới đây vào `docs/v1.2.4/work-packages/<ID>-<slug>/README.md`.

```markdown
# <ID> — <Title>

Status: PLANNED
Owner: <agent/human>
Baseline SHA: <full SHA>
Depends on: <IDs>

## Authority and problem

- Master-spec sections:
- Audit finding:
- Current executable behavior:
- Intended behavior:

## In scope

- Production paths:
- Test paths:
- Documentation/evidence paths:

## Out of scope

- Explicit exclusions:

## Contract

| Input/state | Output/status | Side effects | Failure semantics |
|---|---|---|---|
| | | | |

## Security and compatibility

- Authorization boundary:
- Secret handling:
- Backward compatibility/migration:
- Windows/Linux/macOS considerations:

## Implementation sequence

1. Test/fixture:
2. Smallest production slice:
3. Integration:
4. Negative paths:
5. Documentation/evidence:

## Acceptance commands

```text
<exact sanitized commands>
```

## Required evidence

- Tested full SHA:
- Environment:
- Results:
- Logs/checksums:
- Known limitations:
- Reviewer:

## Rollback

- Reversible code/config action:
- Data remains canonical because:
- Operations requiring maintainer approval:
```

Không đổi status sang `IMPLEMENTED_VERIFIED` nếu bất kỳ trường bắt buộc nào còn trống hoặc acceptance gate chưa đạt.

