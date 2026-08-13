# M10.7 — Large-Corpus Rollout + Benchmark + Final M10 Acceptance — VERIFIED

**Status:** VERIFIED
**Schema / migration version:** v10 (NO new migration; **no `migrate_11`**)
**Authority:** `plan-m10.md` §M10.7, `implementation-plan.json`, `project-state.yaml`, `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
**Starting HEAD:** `c40875b60025736da18391da3b07bc8e7cc56999`
**Historical M10.7 canonical-tested HEAD:** `2e6213700022581a37673cc0bab4a0aaa4facfcd`
**Historical M10.7 canonical result:** **3001 passed, 4 skipped, 0 failed**
**Later state/acceptance commit:** `6224292e453c2392f3a8121b1f1b578006c9768f` (state/acceptance only; canonical at this exact HEAD is **NOT PROVEN**)

---

## 1. Scope

M10.7 is the final M10 increment: prove the M10.1–M10.6 corpus architecture
against a **real large corpus** through the **actual product pipeline**, and
record measured evidence. It is a rollout/benchmark/acceptance increment, not a
feature increment.

**In scope:** real-corpus rollout via the product facade; deterministic
read-only preflight inventory; first-ingest benchmark; second unchanged-sync
idempotence; retrieval benchmark + deterministic sanity; graph projection and
bounded-read benchmark; EvidenceSet end-to-end; derived-rebuild equivalence;
permanent security regressions at real scale; final M10 acceptance.

**Out of scope (NOT performed):** packaging/release engineering; post-M10 audit;
corpus-specific Obsidian projection; OCR mass rollout; semantic embedding of the
corpus; new schema migration; any mandatory new dependency; M10.8; M11.

---

## 2. Real corpus — runtime input only

| Property | Value |
| --- | --- |
| Logical source label | `quantlab-papers` |
| Source path handling | **RUNTIME ONLY** via `ZERO_MEM_M10_CORPUS_PATH` |
| Absolute path in `src/` | **NO** |
| Absolute path in tests / migrations / schema / default config | **NO** |
| Absolute path committed to the repo | **NO** |
| Source folder mutated | **NO** — opened `rb` only |
| Authorization scope | `profile_id=zero-mem`, `project_id=m10-corpus-rollout`, `knowledge_space_id=quant-papers` |
| Authorization derived from path | **NO** — explicit owner-approved scope |

**Relocatable logical reference.** Every source is registered with
`external_ref = "<source_label>/<path relative to the corpus root>"`, never the
absolute path. Verified: identical bytes registered from two different absolute
paths produced **different** `source_id` when the absolute path was used as
`external_ref`, and a **stable** `source_id` under the relocatable form. The
corpus can therefore be relocated (`/mnt/data/QuantLibrary`,
`/home/other/Documents/...`) without minting a new knowledge identity.

---

## 3. Preflight inventory (read-only, zero-LLM)

| Metric | Value |
| --- | --- |
| Filesystem entries scanned | 601 |
| Regular files | 601 |
| PDF files | 601 |
| Other supported formats | 0 |
| Unsupported files | 0 |
| Zero-byte files | 0 |
| Unreadable files | 0 |
| Symlinks | 0 |
| Path-traversal / symlink concerns | none observed |
| Duplicate filenames | 0 |
| Exact byte duplicates | 0 |
| Total source bytes | 1,410,552,914 (1345.2 MiB) |
| Discovery wall time | 0.013 s |

---

## 4. PDF parser status

| Property | Value |
| --- | --- |
| Parser | `pypdf==6.15.0` |
| Installation | project `.venv` **only** (no system-wide, no sudo) |
| Network / cloud | **none** — fully local, offline |
| Requirement class | **OPTIONAL extra**; core Zero-Mem works without it |
| Absence-safe | verified — `PdfAdapter.is_available()` is `False` without it and the TXT path is unaffected |
| OCR | **NOT used**; no OCR mass rollout |

---

## 5. First ingest (601 PDFs, real pipeline)

Measured on this machine; no fabricated figures.

| Metric | Value |
| --- | --- |
| Files discovered | 601 |
| Supported | 601 |
| Successfully registered | 601 |
| Extraction `complete` | 601 |
| Extraction `partial` | 0 |
| `image_only` (scanned) | 0 |
| `corrupt_source` | 0 |
| `parser_unavailable` | 0 |
| Other failures | 0 |
| Failure count | **0** |
| Sources projected | 601 |
| Normalized units projected | **26,144** |
| Units rejected by safety boundary | **4** |
| Distinct source ids | 601 |
| Logical source versions | 601 |
| Exact duplicate content | 0 |
| Distinct unit content hashes | 19,221 |

**Timing / resources**

| Metric | Value |
| --- | --- |
| Register stage | 4.058 s |
| Extraction census stage | 511.791 s |
| Projection stage | 806.555 s |
| Total first ingest | **1322.404 s** (~22.0 min) |
| Throughput | ~0.45 files/s; ~1.07 MiB/s of source bytes |
| Peak RSS (`ru_maxrss`) | 1,208,922,112 B (~1152.9 MiB) |
| Blob/artifact store | 1,410,991,652 B (1345.6 MiB) |
| Derived DB after ingest | 149,504,000 B (142.6 MiB) |

Note: the census stage re-extracts every PDF purely to classify extraction
status for this report; it is benchmark instrumentation, not a product
requirement. Product ingest is the register + projection path.

---

## 6. Ingest failure policy

Zero failures occurred over 601 real PDFs, so no document exercised the failure
path in this run. The policy is nonetheless implemented and exercised by the
focused suite: each source is guarded independently, a failure is recorded with a
deterministic class (`read_error`, `register_error`, `extract_raise`, or the
closed `ExtractionStatus` value), and one malformed document cannot abort the
rollout. Failed documents are never counted as ingested.

Real-world parser warnings were emitted by `pypdf` for many files (wrong-pointing
objects, duplicate `/Rotate` keys, undecodable XObjects). All were tolerated:
extraction still returned `complete` for all 601 files and no warning became a
failure or a silent data loss.

---

## 7. Second unchanged sync — idempotence

Same source folder, unmodified, re-run through the same pipeline.

| Metric | Value |
| --- | --- |
| First-run duration | 1322.404 s |
| Second-run duration | 1139.316 s |
| Files re-registered (idempotent identity) | 601 |
| Distinct source ids | 601 (unchanged) |
| **New sources** | **0** |
| **New units** | **0** |
| **New logical versions** | **0** |
| Logical digest unchanged | **True** (empty diff) |
| Sources / units after sync | 601 / 26,144 (identical) |

Unchanged content created **zero** new logical versions, zero duplicate corpus
units, zero duplicate graph state, and no authorization-identity duplication.

---

## 8. Retrieval benchmark (CORE — lexical + metadata)

Deterministic 22-query set, declared in `benchmarks/run_m10_rollout.py`
**before** any results were observed, including two deliberate no-match
controls. No query was added or removed after seeing scores.

| Metric | Value |
| --- | --- |
| Queries | 22 |
| Hits | 20 |
| No-hits | 2 (both intentional nonsense controls) |
| Median latency | **4.885 ms** |
| p95 latency | **21.214 ms** |
| Max latency | 38.501 ms |
| top-k bound | 10 |
| Deterministic repeat (3 rounds) | **PASS** — byte-identical ordered unit ids |

No latency threshold is defined in the approved plan, so these are reported as a
**measured baseline on this machine at corpus size 601 sources / 26,144 units**,
not as a pass/fail gate and not as a general performance claim.

---

## 9. Retrieval sanity (not a universal quality proof)

Deterministic probe rule declared up front: for each sampled unit, query its
first 5 purely-alphabetic tokens of length >= 4.

Rationale for the rule (documented, not post-hoc tuning): real PDF extraction
splits words across layout runs (`DEVIA TIONS`, `P A THWISE`), and
identifier-like tokens such as `arXiv:1706.05291v3` are normalized by the query
planner to `arxiv1706.05291v3` while the FTS tokenizer splits the indexed text
on `:`. A raw leading-token slice therefore probes tokenizer asymmetry rather
than retrieval. Confirmed by direct probe: `1706.05291v3` alone retrieves the
unit, as do author surnames and title words.

| Class | Result |
| --- | --- |
| Distinctive word phrase -> own unit retrievable | 5/5 PASS |
| Single distinctive term | PASS |
| Multi-term lexical | PASS |
| Metadata-constrained (`project_id`) | PASS |
| No-match control | PASS (empty) |

This is **retrieval sanity**, not a universal answer-quality claim.

---

## 10. Optional semantic retrieval

| Property | Value |
| --- | --- |
| Semantic retrieval used | **NO** |
| Corpus embedded | **NO** |
| Model downloaded | **NO** |
| Cloud embeddings | **NO** |
| Core M10 acceptance depends on semantic | **NO** |

All CORE results above are lexical + metadata only.

---

## 11. Graph (M10.6) over the real corpus

| Metric | Value |
| --- | --- |
| Edges projected | **32,377** |
| `source_of` edges | 26,144 |
| `derived_from` edges | 6,233 |
| Projection duration | 0.939 s |
| Rebuild (re-projection) | equivalent, empty digest diff |
| Bounded read latency | sub-millisecond on the sampled seed |

**Bounds preserved (unchanged from M8 / M10.6):**

| Bound | Ceiling | Observed |
| --- | --- | --- |
| depth | <= 2 | 2 |
| fan-out | <= 20 | 20 |
| nodes | <= 40 | 21 |
| edges | <= 80 | 21 |

Widening is fail-closed: `GraphReadBounds(max_nodes=41)` raises
`graph_bounds_error:exceeds_fixed_ceiling:max_nodes`. Bounds were **not**
increased because the corpus is large.

---

## 12. EvidenceSet end-to-end (25/25 invariants PASS)

Exercised through the real facade (M5 authorization -> M10.5 retrieval ->
M10.6 bounded graph -> M7 EvidenceSet) against a derived store built from the
real corpus.

| Invariant | Result |
| --- | --- |
| Derived store populated from real corpus | PASS (120 sources / 3,041 units) |
| Known real units retrievable by their own words | PASS 5/5 |
| No-match query returns empty | PASS |
| Unauthorized scope retrieves ZERO units | PASS |
| Corpus-only EvidenceSet | PASS |
| All corpus evidence typed `corpus_unit` | PASS |
| Memory-only EvidenceSet still functional | PASS |
| Corpus evidence carries provenance | PASS |
| Foreign profile receives ZERO corpus evidence | PASS |
| Instruction-like corpus text stays DATA | PASS |
| Injection cannot raise EvidenceSet bounds | PASS |
| No secret-bearing unit searchable | PASS (0) |
| Graph bounds (nodes/edges/depth/fan-out) | PASS |
| Unauthorized graph seed leaks no nodes/edges | PASS (0 / 0) |
| Unauthorized graph read flags hidden | PASS |
| Graph bounds cannot exceed M8 ceiling | PASS (fail-closed) |
| Derived store byte-identical after all reads | PASS |

**M7 bounds preserved:** primary <= 5, supporting <= 3, total <= 8 — observed
0 primary / 3 supporting on the corpus-only build.

---

## 13. Security / safety rollout report

| Metric | Value |
| --- | --- |
| Units rejected by the safety boundary | **4** (never stored, counted only) |
| Sources partially affected | rejections are per-unit; the owning sources projected their remaining units normally |
| Secret-bearing searchable results | **0** |
| Secret-bearing graph/enrichment results | **0** |
| Secret material reproduced in this evidence | **NONE** |

**False-positive note (method correction, recorded for honesty).** An initial
E2E secret probe reported 1 match. Investigation showed the probe used SQLite
`LIKE`, which is **case-insensitive** by default, so `%AKIA%` matched the
ordinary word `Slo-vakia` (Slovakia) hyphen-split across a PDF line break. The
probe was corrected to case-sensitive `GLOB`; the true count is **0**. This was a
defect in the verification probe, not in the product, and no secret existed.

Permanent regressions re-run at real scale: hidden-candidate non-influence,
hidden-graph non-influence, M6.6 resource-type isolation, cross-scope identity
isolation, M7 injection/data boundary, M8 graph authorization.

---

## 14. Storage and rebuild

| Metric | Value |
| --- | --- |
| Blob/artifact store | 1345.6 MiB |
| Derived DB (units + FTS + relations) | 142.6 MiB |
| Derived / source ratio | ~0.106 |

**Rebuild:** derived corpus state was dropped and rebuilt from canonical
registry + blobs, then the derived graph was re-projected (a full derived
rebuild spans **both** derived stages, since `rebuild_from_corpus` drops
`zm_corpus_relations` by design).

| Rebuild metric | Value |
| --- | --- |
| Duration | 755.494 s |
| Sources / units after rebuild | 601 / 26,144 |
| Secret rejections after rebuild | 4 (identical) |
| Extraction failures | 0 |
| Graph edges after re-projection | 32,377 (identical) |
| Logical digest diff | **{} (empty)** |
| Digest sha256 | `eeb197d2a656fc117d532f1a3630f2b0305d4937e65aa327131ffbed3b25a148` |
| **Equivalent logical state** | **PASS** |

Compared on stable logical metrics: source ids, unit content hashes, counts,
distinct content hashes, authorization scopes, and relation count. Canonical
JSONL and blobs were never deleted or modified; only derived tables were
dropped.

---

## 15. Read-only guarantee

The derived store was **byte-identical (sha256)** before and after all benchmark
queries, graph reads, and EvidenceSet builds. Canonical `corpus_sources.jsonl`,
source blobs, memory JSONL, and project state were untouched by read paths.
Writes occurred only in the explicit projection / graph-build / rebuild phases.

---

## 16. Defects found in prior verified increments

M10.7 execution surfaced two defects in prior-VERIFIED increments. Both were
reported explicitly and fixed minimally in their **own** commits, separate from
this acceptance evidence.

### 16.1 `fix(tests)` — malformed M10.2 `sample.pdf` fixture

Enabling the optional parser un-skipped a test that then failed. The fixture
declared `xref` offsets and a `startxref` that did not match its own byte layout
(objects 4/5 declared at 206/284, actually at 241/340; `startxref` 340 vs real
table at 410), so a conforming parser resolved the trailer onto
`5 0 obj /Type /Font` and returned `corrupt_source`. The fixture had **always**
been a corrupt PDF; the defect was invisible across M10.2–M10.6 because the only
tests reading it through a real parser were skipped while the parser was absent.

`PdfAdapter` was correct and unchanged (601/601 real PDFs -> `complete`). The
generator now computes offsets from emitted bytes. Two permanent, **parser-
independent** regressions were added so a skip can never re-hide this.

### 16.2 `fix(corpus)` — canonical registry JSONL corrupted by `blob_ref` rebind

**Product defect.** `CorpusSourceRegistry._update_record` read lines with
`splitlines()` (unterminated) but re-inserted records via `_serialize()`
(already `\n`-terminated), then re-joined with `b"\n"` — injecting one **blank
line per rebound record**. Registering N blob-bound sources wrote N blank lines
into `corpus_sources.jsonl`, a state the registry's own `_load()` rejects with
`malformed_historical_line`. The canonical store — the authoritative,
rebuildable one — was being written unreadable, breaking every
reload/rebuild-from-canonical path. This is exactly what blocked the M10.7
second-sync stage and is how the defect was found.

Fixed by normalizing to exactly one terminator per record. Two permanent
regressions added: raw-bytes assertion (no `b"\n\n"`, exact record count) and a
reopen-from-disk replay asserting `source_id -> blob_ref` survives. Both
mutation-tested against the original defect.

---

## 17. Product code changes

| Item | Value |
| --- | --- |
| Product files changed for M10.7 features | **0** |
| Product files changed for a discovered defect | 1 (`src/corpus/registry.py`, §16.2) |
| Schema changes | **NONE** (v10 preserved) |
| New mandatory dependencies | **NONE** |
| New optional dependency | `pypdf==6.15.0`, venv-only, owner-approved |
| Architecture redesign | none |

---

## 18. Benchmark harness

| File | Role |
| --- | --- |
| `benchmarks/m10_benchmark.py` | reusable rollout/benchmark library (plan-designated) |
| `benchmarks/run_m10_rollout.py` | rollout stages + metrics runner |
| `benchmarks/run_m10_e2e.py` | E2E EvidenceSet / security invariant runner |

The harness calls the real public facade at every stage — no fake benchmark path
bypasses product behavior. It is clearly separate from the canonical suite and is
never a substitute for it. Runtime state is written to a temp dir under
`/tmp/hermes-verify-*`; no corpus files, blobs, DBs, or benchmark logs are
committed.

---

## 19. Final M10 architecture invariants

```
Hermes
   |
   v
authorized EvidenceSet
   |
   +---- Memory
   |
   +---- Corpus
            + source registry (canonical JSONL)
            + source blobs/artifacts (canonical)
            + extraction (M10.2, optional PDF parser)
            + normalization (M10.3)
            + dedup / versioning (M10.3)
            + derived SQLite (M10.4, rebuildable)
            + retrieval (M10.5, authorization-first)
            + graph (M10.6, derived + bounded)
            + optional enrichment (absent-safe)
```

| Invariant | Verified |
| --- | --- |
| Memory != Corpus | YES |
| Corpus != Obsidian | YES (no corpus projection performed) |
| SQLite derived != canonical | YES (dropped and rebuilt from canonical) |
| content hash != authorization identity | YES (19,221 distinct hashes, scopes intact) |
| filesystem path != knowledge identity | YES (relocatable logical ref) |
| graph adjacency != authorization | YES (both endpoints required) |
| model output != verified fact | YES (zero LLM in the rollout) |
| optional semantic/enrichment != required core | YES |
| unauthorized data = zero influence | YES |

---

## 20. Zero-LLM / zero-network confirmation

The entire rollout — discovery, registration, extraction, normalization, dedup,
versioning, projection, retrieval, graph, EvidenceSet, rebuild — made **zero LLM
calls and zero network calls**. No PDF was sent through a model context. No
corpus-wide LLM analysis was performed.

---

## 21. Test evidence

| Suite | Result |
| --- | --- |
| M10.1–M10.6 focused groups | 152 passed, 1 skipped |
| Security / authorization regressions (`m5`/`m6_6`/`m7`/`m8`/injection/secret/redact/isolation/authoriz) | 1306 passed |
| E2E real-corpus invariants | **25/25 PASS** |
| PRE-BINDING canonical | **3001 passed, 4 skipped, 0 failed** |
| HISTORICAL FINAL-HEAD canonical (tested at `2e62137`) | **3001 passed, 4 skipped, 0 failed** |

Canonical command (clean isolated HOME):

```
TEST_HOME="$(mktemp -d)"
HOME="$TEST_HOME" .venv/bin/python3 -m pytest tests/ -q
rm -rf "$TEST_HOME"
```

---

## 22. Git hygiene

| Check | Result |
| --- | --- |
| Real PDFs committed | **NO** |
| Blob store committed | **NO** |
| Derived DB committed | **NO** |
| Benchmark runtime data committed | **NO** |
| Absolute corpus path committed | **NO** |
| `.venv` / caches committed | **NO** |

---

## 23. What M10.7 does and does not prove

**Proves:** this architecture processed 601 real PDFs (1345.2 MiB) through the
real product pipeline on this machine with zero ingest failures, remained
deterministic and idempotent, preserved provenance and authorization boundaries
at real scale, kept unauthorized data at zero influence, stayed read-only on
retrieval, and rebuilt derived state to an identical logical projection.

**Does not prove:** performance on other hardware, other corpora, or larger
scales; universal answer quality; behavior of formats other than PDF/TXT; OCR or
scanned-document handling; semantic retrieval quality. No claim of "fast",
"instant", "production-ready", or "scales indefinitely" is made.

---

## 24. Post-M10 status

| Item | Status |
| --- | --- |
| Post-M10 full audit | **NOT STARTED** |
| Packaging / release engineering | **NOT STARTED** |
| Clean-machine install test | NOT STARTED |
| Backup / restore test | NOT STARTED |
| Zero-Mem v1 release | NOT RELEASED |
| M10.8 | **DOES NOT EXIST** |
| M11 | **DOES NOT EXIST / NOT CREATED** |

M10 completion means the Universal Knowledge Corpus milestone is complete. It
does **not** mean the project or a release is complete.
