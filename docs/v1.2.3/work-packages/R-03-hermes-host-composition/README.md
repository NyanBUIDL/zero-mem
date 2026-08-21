# R-03 — Hermes Host Composition

**Status:** OPEN
**Baseline SHA:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Finding closed:** Existing public plugin factory is capture-only and does not prove full host lifecycle composition.
**Allowed paths:** `src/integration/hermes_plugin.py`, `zero_mem/hermes_integration.py`, read/capture adapters, focused R-03 tests, v1.2.3 evidence/work-package documentation.
**Public boundary tested:** Supported host/plugin context factory.
**Platform scope:** Linux first; host lifecycle contract.

## Contract decision

Compose one runtime with capture, projection, read tools, optional injection boundary, restart/shutdown cleanup and duplicate-owner prevention. Hermes remains orchestration/final-action owner.

## Negative cases

Disabled composition, duplicate writer/worker/tool, restart, shutdown, projection lag and denied read.

## Evidence

Pending R-00…R-02 dependency gates.
