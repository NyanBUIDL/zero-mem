# Zero-Mem v1.2.2

## Agent Development System

**Status:** Planning and implementation-control system. It authorizes documentation only; it does not itself authorize a product-code change, commit, push, tag, or release.

This version closes the production-completeness findings left open by v1.2.0/v1.2.1 before feature expansion. It is intended to be read by a human maintainer or an implementation agent from top to bottom.

Start at [agent-development-system/00-START-HERE.md](agent-development-system/00-START-HERE.md). The authoritative master plan is [agent-development-system/04-MASTERPLAN.md](agent-development-system/04-MASTERPLAN.md).

## Scope

- Canonical public read capabilities.
- Runtime-owned projection and observable freshness.
- One canonical sidecar contract.
- Full Hermes composition lifecycle.
- Qualified Windows, Linux, and macOS storage behavior.
- Reproducible, exact-SHA release evidence.

## Non-goals

- New vector database, embeddings, graph algorithms, cloud services, or automatic context injection.
- Rewriting v1.1/v1.2 historical evidence.
- Replacing JSONL canonical truth with SQLite, Obsidian, or an index.

Every change must follow the state machine in [03-AGENT-DELIVERY-PROTOCOL.md](agent-development-system/03-AGENT-DELIVERY-PROTOCOL.md) and satisfy the gates in [06-TEST-EVIDENCE-AND-RELEASE.md](agent-development-system/06-TEST-EVIDENCE-AND-RELEASE.md).
