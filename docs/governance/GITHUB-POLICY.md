# Zero-Mem Git/GitHub Governance Policy

**Status:** Mandatory repository policy
**Scope:** Every Git or GitHub mutation against Zero-Mem
**Authority:** Repository governance, subject to the higher-authority sources named in [`AGENTS.md`](../../AGENTS.md)

## 1. Purpose and authority

This document converts the Zero-Mem GitHub interaction guide into a mandatory
agent policy. It governs commits, branch creation or update, merge, rebase,
tagging, push, GitHub Release operations, hotfixes, rollback, and remote
modification.

Agents **MUST** read this policy before any such mutation. A read-only inspection
is required first and does not itself authorize a mutation.

Higher-authority governance remains controlling. In particular, the master
specification, approved ADRs, approved work-package scope, release gates, and
explicit maintainer authorization **MUST** be preserved. This policy **MUST NOT**
be interpreted as authorization to publish, release, rewrite history, or modify
product source code.

## 2. Canonical identity and remote verification

The canonical GitHub repository is:

```text
NyanBUIDL/zero-mem
```

The expected GitHub remote URL is:

```text
git@github.com:NyanBUIDL/zero-mem.git
```

The canonical local development repository is the repository root containing
this policy. A preparation clone, worktree, or local `origin` **MUST NOT** be
assumed to be canonical merely because it has the same object database or
remote.

Before a Git/GitHub mutation, an agent **MUST** inspect and record, without
exposing secrets:

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
git remote -v
git remote get-url github
git branch -vv
```

The agent **MUST** verify that the intended push remote resolves to the
canonical GitHub repository. A local preparation repository, filesystem path,
unexpected hostname, or ambiguous `github` remote is not an acceptable target.
If the canonical remote is ambiguous or cannot be verified, **STOP** and emit
`ESCALATION_REQUIRED`.

Remote modification itself is governed by this policy. An agent **MUST NOT**
add, remove, rename, or repoint a remote without explicit authorization and a
before/after verification record.

## 3. Branch model and stable history

Zero-Mem uses this branch model:

```text
master          = latest stable
release/v1.1.0  = v1.1 maintenance line
release/v1.2.0  = v1.2 maintenance line
release/vX.Y.Z  = corresponding maintenance line
```

`master` **MUST** represent the latest stable line. A release branch **MUST**
remain the maintenance line for its corresponding version family and **MUST NOT**
be silently repurposed for another release.

New release work **SHOULD** start from the latest verified `master` using a
fast-forward-only update. A release branch **MUST** be created only with
explicit scope and **MUST** be named `release/vX.Y.Z` for the corresponding
line. Agents **MUST NOT** create version directories as a substitute for Git
branching.

`master` and published release branches are protected history. Agents **MUST
NOT** force-push, rewrite, or silently delete them. Deletion of a release
branch requires explicit maintainer authorization, a preservation/rollback
record, and verification that no supported maintenance or release provenance
would be lost.

## 4. Commit and working-tree rules

Before staging or committing, the agent **MUST** classify every dirty path as
one of:

```text
EXPECTED_SOURCE_CHANGE
EXPECTED_TEST_CHANGE
EXPECTED_DOC_CHANGE
EXPECTED_EVIDENCE
GENERATED_ARTIFACT
UNRELATED
USER_DATA
UNKNOWN
```

`UNKNOWN`, `USER_DATA`, and unrelated paths **MUST NOT** be committed without
explicit authorization. The agent **MUST NOT** use `git add .` or an equivalent
broad staging operation when the working tree contains unclassified artifacts.
Staging **MUST** name the authorized paths explicitly.

The agent **MUST** run `git diff --check` before committing and **SHOULD** use
small, traceable commits with imperative messages that identify the change.
Secrets, credentials, private paths, generated clutter, and unverified claims
**MUST NOT** enter a commit.

An unknown dirty working tree is a stop condition. The agent **MUST NOT** use
destructive cleanup to manufacture a clean tree. **STOP** and emit
`ESCALATION_REQUIRED` when unknown files or unexplained modifications are
present.

## 5. Release workflow and SHA invariant

A release requires separate authorization and independent release qualification.
The normative order is:

```text
verified release branch commit
→ fast-forward master
→ verify release SHA invariant
→ create an immutable tag
→ verify remote refs
→ push explicitly authorized refs
→ verify remote refs and artifacts
→ create/update the GitHub Release only after tag verification
```

The release invariant **MUST** hold for every release:

```text
MASTER_SHA
=
RELEASE_BRANCH_SHA
=
TAG_TARGET
=
ARTIFACT_SOURCE_SHA
```

`ARTIFACT_SOURCE_SHA` **MUST** identify the exact source revision used to build
and qualify the published artifacts. A release **MUST NOT** proceed when any
member differs, is abbreviated ambiguously, or cannot be independently
verified. An invariant mismatch is a hard stop: **STOP** and emit
`ESCALATION_REQUIRED`.

Before a release push, the agent **MUST** compare local and remote refs with
full object IDs, for example:

```bash
git rev-parse master
git rev-parse release/vX.Y.Z
git rev-list -n 1 vX.Y.Z
git ls-remote github refs/heads/master
git ls-remote github refs/heads/release/vX.Y.Z
git ls-remote github refs/tags/vX.Y.Z
git rev-list --left-right --count master...release/vX.Y.Z
```

A release branch merge into `master` **SHOULD** be fast-forward-only. If it is
not fast-forwardable, the agent **MUST NOT** blindly merge or rebase. It **MUST**
inspect the divergence, preserve both histories, and **STOP** for maintainer
resolution.

## 6. Tags and GitHub Releases

A version tag `vX.Y.Z` **MUST** point to the verified release commit and **MUST**
be treated as immutable after publication. An agent **MUST NOT** move, delete,
retarget, or recreate a published tag. If a tag already points to another SHA,
**STOP** and emit `ESCALATION_REQUIRED`.

A GitHub Release is a publication layer attached to a tag; a branch or tag alone
is not a GitHub Release. The release operator **MUST** verify the tag target,
source SHA, artifact hashes, release notes, and asset provenance before creating
the GitHub Release. Existing releases **MUST NOT** be edited or replaced to
conceal a provenance or SHA mismatch.

Release assets **MUST** be built from the exact `ARTIFACT_SOURCE_SHA` and
**MUST** be checked for secrets, unintended files, and reproducibility before
upload. A release operation remains unauthorized unless its own release gate
and publication approval are present.

## 7. Push rules

Pushes **MUST** name the verified canonical remote and explicit refs. The
operator **MUST NOT** push to a local preparation remote by mistake and **MUST
NOT** use an unverified remote.

By default, the following are prohibited:

- `git push --force`;
- `git push --force-with-lease` against `master` or release history;
- any published-history rewrite;
- deletion of stable or release refs;
- pushing a tag whose target is not the verified release SHA;
- pushing before required checks, review, and authorization pass.

A rejected non-fast-forward push is a safety signal, not permission to force.
The agent **MUST** fetch/inspect the remote state and resolve the cause through
an authorized additive commit or maintainer decision.

## 8. Hotfix flow

A hotfix for a published maintenance line **MUST** be additive:

1. verify the canonical remote and `release/vX.Y.Z` branch;
2. update it with `--ff-only` after reviewing divergence;
3. implement and test the smallest authorized fix;
4. commit the fix without rewriting existing history;
5. create the next patch tag, such as `v1.2.1`, only after qualification;
6. verify the new release invariant and artifact source SHA;
7. push only explicitly authorized refs; and
8. update the GitHub Release only for the new patch release, as authorized.

The prior tag, for example `v1.2.0`, **MUST NOT** move. A hotfix **SHOULD** be
forward-ported to `master` through the approved integration path so stable
history does not permanently lose the correction; this is a separate change
that requires its own verification.

## 9. Rollback policy

Rollback **MUST** preserve public history and provenance. For local, unpushed
work where retaining the changes is required, a soft reset **MAY** be used only
with explicit scope and known state. For published commits, the default rollback
is an additive `git revert`, not reset, rebase, tag movement, or force push.

Rollback **MUST NOT** delete canonical evidence, release assets, tags, branches,
or working-tree files merely to restore appearance. If the rollback target,
public state, or artifact provenance is unclear, **STOP** and emit
`ESCALATION_REQUIRED`.

## 10. Divergence and conflict handling

An agent **MUST** inspect divergence before merge, rebase, branch update, hotfix,
or push. The following is an inspection aid:

```bash
git log --oneline --left-right --graph master...release/vX.Y.Z
git rev-list --left-right --count master...release/vX.Y.Z
```

Unexplained divergence, an unexpected branch tip, a non-fast-forward stable
update, conflicting release provenance, or a merge that would silently discard
history is a hard stop. The agent **MUST NOT** blind-merge, blind-rebase, reset,
or delete refs to make the graph appear consistent. **STOP** and emit
`ESCALATION_REQUIRED` until a maintainer resolves the graph and required
invariants.

## 11. Branch protection expectations

The GitHub repository **SHOULD** protect `master` and every active release
branch with:

- force pushes disabled;
- deletion disabled;
- required status checks;
- required review/PR approval where appropriate;
- restricted direct pushes for stable and release refs; and
- auditable tag and release permissions.

If the observed GitHub settings do not provide these protections, an agent
**MUST** treat the gap as a governance risk and **SHOULD** report it. The agent
**MUST NOT** bypass the gap by force pushing or rewriting history.

## 12. Forbidden destructive commands

The following commands **MUST NOT** be used casually and are forbidden by
default for Zero-Mem stable/release work:

```text
git reset --hard
git clean -fd
git push --force
git push --force-with-lease
git rebase
git tag -f
git branch -D
git push <remote> --delete <stable-or-release-ref>
```

Use of any such operation requires explicit maintainer authorization, a saved
before-state, a documented rollback plan, and a verified reason it cannot be
replaced by an additive operation. Published-history rewrite remains forbidden
unless a higher-authority decision explicitly authorizes it; otherwise **STOP**
and emit `ESCALATION_REQUIRED`.

## 13. Mandatory stop conditions

The agent **MUST STOP** and report `ESCALATION_REQUIRED` without continuing when
any of the following occurs:

- canonical remote identity is ambiguous or unverified;
- the current or target branch is unexpected;
- release or stable history has unexplained divergence;
- a tag already points to another SHA;
- unknown or unclassified dirty working-tree files exist;
- `MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA` fails;
- the operation requires published-history rewrite;
- a push is rejected or would not be fast-forward-only;
- required release qualification, authorization, or review evidence is missing;
- a command would alter an existing branch, tag, remote, or GitHub Release beyond
  its explicitly authorized scope; or
- provenance, artifact identity, or rollback ownership cannot be established.

A stop is a successful safety outcome. The agent **MUST NOT** guess, retry
blindly, weaken the invariant, or convert an escalation into an implicit
approval.

## 14. Required mutation record

For every completed Git/GitHub mutation, the agent **MUST** record the scope,
authorization, repository identity, branch and commit SHAs, remote verification,
changed refs, checks run, and any remaining risk. The record **SHOULD** be stored
in the repository's approved evidence or handoff location without secrets.

This policy integration itself is documentation-only. It changes no product
source, branch, tag, remote, push, GitHub Release, or release history.
