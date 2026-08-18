# Authorization Schema

Each task authorization must record:

- `task_id`, `wp_id`, `parent_state`, `dependency_state`;
- exact `implementation_paths`, `integration_paths`, `test_paths`, `security_test_paths`, `benchmark_paths`, `evidence_paths`, `handoff_paths`;
- forbidden paths: canonical specification, Product Memory stores, unrelated WPs, remote Git;
- `production_call_graph` with entry point, caller, authority boundary, implementation owner, integration point, consumer;
- pre-mutation hashes and rollback expectation;
- required focused, integration, negative/security, compatibility, migration, and benchmark checks;
- authorization source and expiry at task/WP closure.

Authorization precedes source mutation, retrieval, ranking, context influence, projection write-back, and transport exposure.
