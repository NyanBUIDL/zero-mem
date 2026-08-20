# V122-01 Platform Qualification Checklist

Use only on real future machines/CI. Every checked item must be bound to the exact candidate SHA, raw log, exit code, elapsed time, environment, test counts, and log SHA-256.

## Windows machine

- [ ] checkout exact v1.2.3 candidate
- [ ] verify SHA/tree and isolated Python environment
- [ ] focused platform tests
- [ ] identity
- [ ] locking: shared/shared, shared/exclusive, exclusive/shared, exclusive/exclusive
- [ ] abandoned lock and timeout
- [ ] reparse/path safety
- [ ] atomic promotion
- [ ] JSONL capture and short-write handling
- [ ] recovery
- [ ] WP-33
- [ ] full regression
- [ ] wheel
- [ ] sdist
- [ ] clean install smoke
- [ ] evidence hashes and manifest
- [ ] exact-tree independent review

## macOS machine

- [ ] checkout exact v1.2.3 candidate
- [ ] verify SHA/tree and isolated Python environment
- [ ] focused platform tests
- [ ] POSIX identity and no-follow/path safety
- [ ] locking: shared/shared, shared/exclusive, exclusive/shared, exclusive/exclusive
- [ ] abandoned lock and timeout
- [ ] atomic promotion
- [ ] JSONL capture and short-write handling
- [ ] recovery
- [ ] WP-33
- [ ] full regression
- [ ] wheel
- [ ] sdist
- [ ] clean install smoke
- [ ] evidence hashes and manifest
- [ ] exact-tree independent review

## Evidence rule

A skipped, emulated, or unavailable platform test is `NOT VERIFIED`, never PASS. Preserve the implementation and tests when a row fails; classify the failure before remediation.
