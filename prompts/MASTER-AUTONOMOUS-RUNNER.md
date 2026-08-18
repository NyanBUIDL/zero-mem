# MASTER-AUTONOMOUS-RUNNER

Resume from `project-state.yaml` and `artifacts/tasks/task-manifest.json`. Verify source identity, planning ref, canonical hash, branch, worktree status, and Product Memory exclusions. Select only dependency-ready tasks. Before source mutation, materialize exact task scope and the production call graph. Execute the task rail, then closure and one remediation cycle at most. After verification, run full regression, update evidence/handoff/Development Memory/state, run `git diff --check`, and create a local checkpoint commit. Never push or publish.

If an inconsistency is stale governance projection, reconcile it in the approved control-plane scope. If it is an ordinary implementation defect, repair and retest. Stop only for a true external blocker.
