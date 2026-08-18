# Zero-Mem v1.1 Migration and Rollback Runbook

1. Create and verify a backup before migration.
2. Preview configuration and descriptor changes without mutating canonical memory.
3. Stage derived rebuild and schema validation in an isolated destination.
4. Promote atomically only after verification succeeds.
5. On interruption or failure, restore the verified rollback directory and rerun doctor.
6. Preserve canonical JSONL and rollback evidence; never use migration to delete history.

The supported migration path is local-only and keeps credentials out of descriptors and reports.
