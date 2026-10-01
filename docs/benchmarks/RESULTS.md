# Retrieval quality benchmarks (T7, DEF-061)

Task T7 of `docs/plans/SHARED-MEMORY-RUNTIME-PLAN.md`. Measured on 2026-10-01 in the build sandbox (4 vCPU Linux, Python 3.13,
no GPU, no network except the proxy) against the integration tip `e66f0d8` ("Merge T5 memory library") as baseline. Code under
test: branch `worktree-agent-aefe3f530724468f3`, ranking code at `cd846d6`. Every number below was produced by
`benchmarks/memory_qa_benchmark.py` through the real pipeline (`Memory.add` write path, `Memory.recall` authorized read path); the
raw JSON reports are reproducible with the commands in section 11. Zero LLM calls, zero new runtime dependencies, deterministic
(two processes with the same seed print the same ranking fingerprint).

## 1. Summary

* LoCoMo10, turn-level, one memory per turn (the T5 benchmark): hit@10 **0.6372 -> 0.6907**, recall@10 **0.5862 -> 0.6313**,
  MRR 0.4497 -> 0.4964. The retired lexical store scored 0.6307 / 0.5829.
* Ingesting a conversation the way a user ingests a chat log (one memory per session, one unit per turn) lets the ranking use
  the order of the units: hit@10 **0.7891**, recall@10 **0.7352** on the same questions and gold turns (T5 ranking: 0.6372 / 0.5865).
* LoCoMo session-level: hit@10 0.9384 -> **0.9596**, recall@10 0.8958 -> **0.9240**.
* **LongMemEval itself could not be measured**: `huggingface.co` answers HTTP 403 to the sandbox proxy (organization egress
  policy; not retried, not routed around). The session-level pipeline was exercised on a **synthetic** LongMemEval-format file
  (`benchmarks/synth_longmemeval.py`); its numbers are not LongMemEval numbers (section 10).
* Median `Memory.recall` latency on a LoCoMo conversation **29 -> 7 ms** (p95 41 -> 9 ms), because of three behaviour-neutral
  performance fixes. On a 13k-unit store the new ranking is slower than the old AND-first one (p50 31-46 ms vs 1-2 ms, section 9).
* One authorization finding (hidden rows decided the AND/OR fallback) was fixed and pinned by black-box tests (section 8).

## 2. What is and is not measured

Measured: **retrieval** quality against gold evidence. hit@k = a gold item is in the first k distinct ranked items; recall@k =
fraction of the gold items in the first k; MRR = reciprocal rank of the first gold item over the retrieved list (at most 40 units for
per-turn ingest, 200 for per-session ingest). Ranked items are distinct memories (A), distinct sessions (C, D) or distinct turns (B).

Not measured: the official LoCoMo and LongMemEval scores are **LLM-judged answer accuracy** over a generated answer; none of that is
computed here. A retrieval gain is a necessary, not a sufficient, condition for a better answer. There is no semantic matching
anywhere in this pipeline: it is lexical (SQLite FTS5 discovery plus a Python BM25), so paraphrases without shared words are
out of reach by construction.

## 3. Datasets and configurations

| id | dataset | gold | what is one memory | questions |
|---|---|---|---|---|
| A | LoCoMo10 (`locomo10.json`, snap-research/locomo, 10 conversations, 5,882 turns) | the `evidence` turns | one turn | 1,982 (4 without evidence skipped; 9 have a gold id that matches no turn) |
| B | LoCoMo10 | the `evidence` turns | one session (one unit per turn, so neighbors exist) | 1,982 |
| C | LoCoMo10 | the sessions holding the evidence turns | one session | 1,982 |
| D | **synthetic** LongMemEval-format, seed 7, 120 questions x 40 sessions | `answer_session_ids` | one session | 120 |

A is the configuration T5 reported (`hit@10 0.6372`, `recall@10 0.5862`); it re-measures to the same four digits at `e66f0d8`.
LoCoMo category ids are reported as in the file (1 multi-hop, 2 temporal, 3 open-domain, 4 single-hop, 5 adversarial in the
LoCoMo paper). The synthetic generator builds six LongMemEval question types from templates with deliberate lexical gaps
(inflection, synonyms, hard negatives that share words but not the fact); it is documented in `benchmarks/synth_longmemeval.py`.

## 4. Results: baseline vs final

"Lexical store" = the retired `zero_mem.notes.NotesStore` (FTS5 `bm25()`, OR of exact terms), restored from git history
(`755b40b^`) into a scratch directory and run through the same harness. "Memory at T5" = the ranking of `e66f0d8`. "Memory final"
= this change. `type` rows show T5 -> final.

### A. LoCoMo10 - turn gold, one memory per turn (1982 questions)

| metric | lexical store (retired) | Memory at T5 | Memory final | final vs T5 |
|---|---|---|---|---|
| hit@1 | 0.3214 | 0.3537 | **0.3981** | +0.0444 |
| hit@5 | 0.5489 | 0.5616 | **0.6150** | +0.0534 |
| hit@10 | 0.6307 | 0.6372 | **0.6907** | +0.0535 |
| recall@1 | 0.2960 | 0.3274 | **0.3642** | +0.0368 |
| recall@5 | 0.5090 | 0.5170 | **0.5616** | +0.0446 |
| recall@10 | 0.5829 | 0.5862 | **0.6313** | +0.0451 |
| mrr | 0.4261 | 0.4497 | **0.4964** | +0.0467 |

By question type (T5 -> final):

| type | n | hit@1 | hit@5 | hit@10 | recall@10 | MRR |
|---|---|---|---|---|---|---|
| cat1 | 282 | 0.174 -> 0.252 | 0.365 -> 0.532 | 0.479 -> 0.652 | 0.251 -> 0.373 | 0.271 -> 0.379 |
| cat2 | 321 | 0.439 -> 0.495 | 0.632 -> 0.676 | 0.692 -> 0.735 | 0.658 -> 0.704 | 0.526 -> 0.575 |
| cat3 | 92 | 0.141 -> 0.152 | 0.293 -> 0.359 | 0.348 -> 0.413 | 0.252 -> 0.314 | 0.213 -> 0.251 |
| cat4 | 841 | 0.384 -> 0.429 | 0.605 -> 0.642 | 0.677 -> 0.712 | 0.660 -> 0.694 | 0.486 -> 0.526 |
| cat5 | 446 | 0.392 -> 0.413 | 0.608 -> 0.626 | 0.684 -> 0.700 | 0.676 -> 0.691 | 0.489 -> 0.508 |

### B. LoCoMo10 - turn gold, one memory per session (1982 questions)

| metric | lexical store (retired) | Memory at T5 | Memory final | final vs T5 |
|---|---|---|---|---|
| hit@1 | 0.3209 | 0.3537 | **0.4077** | +0.0540 |
| hit@5 | 0.5489 | 0.5626 | **0.6948** | +0.1322 |
| hit@10 | 0.6307 | 0.6372 | **0.7891** | +0.1519 |
| recall@1 | 0.2958 | 0.3274 | **0.3709** | +0.0435 |
| recall@5 | 0.5090 | 0.5180 | **0.6389** | +0.1209 |
| recall@10 | 0.5829 | 0.5865 | **0.7352** | +0.1487 |
| mrr | 0.4269 | 0.4508 | **0.5312** | +0.0804 |

By question type (T5 -> final):

| type | n | hit@1 | hit@5 | hit@10 | recall@10 | MRR |
|---|---|---|---|---|---|---|
| cat1 | 282 | 0.174 -> 0.262 | 0.365 -> 0.546 | 0.479 -> 0.684 | 0.252 -> 0.389 | 0.273 -> 0.392 |
| cat2 | 321 | 0.439 -> 0.492 | 0.632 -> 0.692 | 0.692 -> 0.763 | 0.658 -> 0.737 | 0.526 -> 0.583 |
| cat3 | 92 | 0.141 -> 0.185 | 0.293 -> 0.348 | 0.348 -> 0.424 | 0.252 -> 0.331 | 0.216 -> 0.268 |
| cat4 | 841 | 0.384 -> 0.442 | 0.608 -> 0.744 | 0.677 -> 0.832 | 0.660 -> 0.826 | 0.487 -> 0.569 |
| cat5 | 446 | 0.392 -> 0.419 | 0.608 -> 0.769 | 0.684 -> 0.868 | 0.676 -> 0.864 | 0.490 -> 0.566 |

### C. LoCoMo10 - session gold, one memory per session (1982 questions)

| metric | lexical store (retired) | Memory at T5 | Memory final | final vs T5 |
|---|---|---|---|---|
| hit@1 | 0.6271 | 0.6584 | **0.7059** | +0.0475 |
| hit@5 | 0.8744 | 0.8759 | **0.9097** | +0.0338 |
| hit@10 | 0.9390 | 0.9384 | **0.9596** | +0.0212 |
| recall@1 | 0.5804 | 0.6118 | **0.6551** | +0.0433 |
| recall@5 | 0.8223 | 0.8239 | **0.8578** | +0.0339 |
| recall@10 | 0.8977 | 0.8958 | **0.9240** | +0.0282 |
| mrr | 0.7387 | 0.7584 | **0.7966** | +0.0382 |

By question type (T5 -> final):

| type | n | hit@1 | hit@5 | hit@10 | recall@10 | MRR |
|---|---|---|---|---|---|---|
| cat1 | 282 | 0.454 -> 0.518 | 0.762 -> 0.858 | 0.886 -> 0.947 | 0.646 -> 0.748 | 0.599 -> 0.667 |
| cat2 | 321 | 0.651 -> 0.679 | 0.841 -> 0.888 | 0.906 -> 0.938 | 0.892 -> 0.927 | 0.738 -> 0.769 |
| cat3 | 92 | 0.359 -> 0.315 | 0.652 -> 0.674 | 0.772 -> 0.804 | 0.642 -> 0.682 | 0.502 -> 0.487 |
| cat4 | 841 | 0.725 -> 0.775 | 0.920 -> 0.937 | 0.967 -> 0.977 | 0.966 -> 0.977 | 0.814 -> 0.849 |
| cat5 | 446 | 0.729 -> 0.794 | 0.935 -> 0.955 | 0.975 -> 0.982 | 0.975 -> 0.982 | 0.823 -> 0.864 |

### D. Synthetic LongMemEval-format - session gold, one memory per session (120 questions)

| metric | lexical store (retired) | Memory at T5 | Memory final | final vs T5 |
|---|---|---|---|---|
| hit@1 | 0.7417 | 0.7333 | **0.7833** | +0.0500 |
| hit@5 | 0.8500 | 0.8500 | **0.8500** | +0.0000 |
| hit@10 | 0.8667 | 0.8667 | **0.8667** | +0.0000 |
| recall@1 | 0.5833 | 0.5750 | **0.6250** | +0.0500 |
| recall@5 | 0.8500 | 0.8500 | **0.8500** | +0.0000 |
| recall@10 | 0.8667 | 0.8667 | **0.8667** | +0.0000 |
| mrr | 0.7938 | 0.7914 | **0.8164** | +0.0250 |

By question type (T5 -> final):

| type | n | hit@1 | hit@5 | hit@10 | recall@10 | MRR |
|---|---|---|---|---|---|---|
| knowledge-update | 15 | 0.600 -> 0.600 | 0.600 -> 0.600 | 0.600 -> 0.600 | 0.600 -> 0.600 | 0.600 -> 0.600 |
| multi-session | 29 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 |
| single-session-assistant | 12 | 0.500 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 | 0.750 -> 1.000 |
| single-session-preference | 9 | 0.000 -> 0.000 | 0.111 -> 0.111 | 0.333 -> 0.333 | 0.333 -> 0.333 | 0.069 -> 0.069 |
| single-session-user | 16 | 0.312 -> 0.312 | 0.750 -> 0.750 | 0.750 -> 0.750 | 0.750 -> 0.750 | 0.521 -> 0.521 |
| temporal-reasoning | 39 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 | 1.000 -> 1.000 |

Reading the tables: A, B and C improve on every aggregate metric; the largest gains are the multi-hop (cat1) questions. In C,
open-domain questions (cat3) lose a little at rank 1 (0.359 -> 0.315, 92 questions) while gaining at ranks 5 and 10. In D the only
movements are at rank 1 (single-session-assistant 0.50 -> 1.00); hit@5/10 are flat because the remaining misses (knowledge-update
"which city do I live in now", preference questions, "which novel did I finish") need meaning, not words.

## 5. Latency and ingest throughput

`Memory.recall` wall time per query (`limit` 40 or 200 units as in section 2) on an otherwise idle machine, one process (the T5 rows of B, C and D
reuse stores built earlier, so their page cache is warm):

| config | engine | recall p50 ms | recall p95 ms | recall mean ms | ingest adds | adds/s |
|---|---|---|---|---|---|---|
| A | lexical store | 0.7 | 0.9 | 0.7 | 5882 | 573.9 |
| A | Memory at T5 | 29.3 | 40.7 | 28.4 | 5882 | 387.7 |
| A | Memory final | 7.2 | 9.2 | 7.4 | 5882 | 366.2 |
| B | lexical store | 1.3 | 1.6 | 1.3 | 272 | 252.4 |
| B | Memory at T5 | 28.1 | 39.8 | 27.3 | - | - |
| B | Memory final | 8.1 | 9.8 | 8.1 | 272 | 119.2 |
| C | lexical store | 1.3 | 1.6 | 1.3 | 272 | 267.7 |
| C | Memory at T5 | 28.0 | 39.2 | 27.1 | - | - |
| C | Memory final | 8.0 | 9.8 | 8.1 | 272 | 124.4 |
| D | lexical store | 0.5 | 1.1 | 0.6 | 4800 | 363.5 |
| D | Memory at T5 | 12.6 | 30.5 | 17.1 | - | - |
| D | Memory final | 8.3 | 19.8 | 9.8 | 4800 | 156.5 |

"Memory at T5" ingest is the unchanged write path (the first run of this session, before any T7 change, measured 387.7 adds/s on A); the T7 changes do not touch it. The retired
store has no authorization, registry, secret pre-scan or blob store, hence the faster ingest and sub-millisecond queries. The
p95 budget of the task (<= 50 ms on a LoCoMo-size store) is met with a wide margin (p95 9-10 ms; the synthetic haystacks of D
are queried cold, one fresh store per question, so their p95 is dominated by page-cache misses: 20 ms).

## 6. What was kept, and why

Every change was kept only after a measured delta on the real data (LoCoMo) without regressing the other configurations by more
than 0.01; the acceptance bar for a *ranking* change was >= 0.005 absolute hit@10 or recall@10 on a real configuration. Parameters
were tuned on the first five conversations and validated on the last five (and the reverse where noted); the table shows full-set
numbers.

Leave-one-out on the final code (each row removes one change; hit@10 / recall@10, D shows hit@1 because hit@10 is flat):

| removed | A turn | B turn-in-session | C session | D synthetic hit@1 |
|---|---|---|---|---|
| nothing (final) | 0.6907 / 0.6313 | 0.7891 / 0.7352 | 0.9596 / 0.9240 | 0.7833 |
| English stemming | 0.6660 / 0.6126 | 0.7679 / 0.7174 | 0.9506 / 0.9108 | 0.7333 |
| coordination factor | 0.6831 / 0.6256 | 0.7770 / 0.7241 | **0.9637 / 0.9313** | 0.7833 |
| neighbor propagation | 0.6907 / 0.6313 | 0.6912 / 0.6318 | 0.9576 / 0.9205 (hit@1 0.7059 -> 0.6720) | 0.7833 |
| BM25 k1 0.6 / b 0.3 (back to 1.2 / 0.75) | 0.6857 / 0.6276 | 0.7846 / 0.7318 | 0.9596 / 0.9260 | 0.7833 |

Note the coordination factor costs session-level C 0.004 hit@10 / 0.007 recall@10 (it is a net win on the turn-level
configurations, +0.008 and +0.012); it is the one kept change with a measured downside, within the 0.01 allowance.

Cumulative ladder, measured with a flag-controlled build of the same code during development (neighbor propagation there was
the simpler additive form and the coordination exponent 0.3; the final code differs from step 5 only by the refinements of items 5 and 6 below: hit@10 A -0.002, B +0.001, C +0.001):

| step | A h@10 / r@10 / MRR | B h@10 / r@10 / MRR | C h@10 / r@10 / MRR | D h@1 / MRR |
|---|---|---|---|---|
| 0 T5 ranking | 0.6372 / 0.5862 / 0.4497 | 0.6372 / 0.5865 / 0.4508 | 0.9384 / 0.8958 / 0.7584 | 0.7333 / 0.7914 |
| 1 + one OR query ranked by BM25 (was AND-first with OR fallback) | 0.6519 / 0.6002 / 0.4530 | 0.6519 / 0.6005 / 0.4542 | 0.9485 / 0.9088 / 0.7623 | 0.7250 / 0.7872 |
| 2 + BM25 k1 0.6, b 0.3 | 0.6630 / 0.6091 / 0.4729 | 0.6630 / 0.6091 / 0.4742 | 0.9475 / 0.9087 / 0.7750 | 0.7250 / 0.7872 |
| 3 + Porter stemming | 0.6831 / 0.6256 / 0.4881 | 0.6842 / 0.6263 / 0.4892 | 0.9612 / 0.9248 / 0.7823 | 0.7833 / 0.8164 |
| 4 + coordination factor | 0.6927 / 0.6331 / 0.4977 | 0.6937 / 0.6342 / 0.4988 | 0.9561 / 0.9194 / 0.7796 | 0.7833 / 0.8164 |
| 5 + neighbor propagation | 0.6927 / 0.6331 / 0.4976 | 0.7881 / 0.7333 / 0.5368 | 0.9586 / 0.9240 / 0.8021 | 0.7833 / 0.8162 |

What each kept change is:

1. **One OR discovery query ranked by BM25** instead of "AND of every term, OR only if nothing matched" (+0.015 hit@10 on A and +0.010
   on C). The old form returned only the units that contained *every* word of a natural-language question; the answer unit usually
   lacks some of them. Units covering more of the query still rank first (coordination factor, BM25 sum).
2. **BM25 k1 = 0.6, b = 0.3** (was 1.2 / 0.75). The units are chat turns, paragraphs and notes, where a long unit is not a noisier one.
   Held-out half (conversations 6-10, config A): default hit@10 0.6437, (k1 0.8, b 0.3) 0.6518, (0.4, 0.2) 0.6579; hit@1 +0.027.
   Tuned on LoCoMo only; see the limits.
3. **Porter stemming** (`src/corpus/stemming.py`, stdlib, verified against the published examples). Plain ASCII words of >= 4 letters
   are compared by stem ("adopted" ~ "adopting" ~ "adoption"; "living" ~ "live"); FTS5 cannot stem, so discovery matches the root every
   inflected form shares as a prefix and the scorer rejects false friends ("studies" does not match "student"). Short words, digits,
   accented and non-Latin text keep the previous prefix semantics, and the Vietnamese diacritic folding is unchanged.
   +0.020 hit@10 on A, +0.014 on C, +0.058 hit@1 on D.
4. **Coordination factor** `(matched terms / query terms) ^ 0.6` for queries of two or more terms (see the downside above).
5. **Neighbor propagation** (the "adjacent-turn context" idea, done at ranking time so that the metric stays honest: a neighbor
   consumes a result slot like any other unit). A unit also scores 0.7 x the best score of the units within two positions in the same
   source, weighted by the fraction of that neighbor's matched query terms the unit does *not* contain; neighbors of the best ten hits
   that matched nothing enter with 0.7 x the hit's score (never above it). The answer turn of a dialogue rarely repeats the words of
   the question turn, so it was missing from the top 10 although its neighbor ranked first. B: hit@10 0.6912 -> 0.7891, recall@10
   0.6318 -> 0.7352. It only exists when a source has several units (a session, a note, a file), not for one-memory-per-turn ingest.
   The first additive form (unit score + 0.5 x neighbor score) gave the same LoCoMo gain but let a run of adjacent rows or paragraphs
   that all contain the same words lift each other above an isolated exact match on documents (self-retrieval p@1 0.667, section 9);
   the coverage-aware form restores p@1 to 0.749 at equal LoCoMo hit@10.
6. **Bounded candidate window**: at most 500 units are scored, chosen by how many query terms a unit contains (then registration
   order). It replaces truncation by registration order (the T5 hand-off: the discovery cap counted before the scope filter) and caps
   the per-query cost on large stores. Window sizes 250 / 400 / 700 changed A hit@10 by -0.0035 / -0.0015 / 0 relative to 1000 (measured on the build before the coverage-aware propagation); 500 was chosen.
7. **Performance, behaviour neutral** (identical ranking fingerprints before and after): regex tokenizer and per-text token cache
   (29 -> 16 ms median), one copy of the frozen hit instead of three per candidate (16 -> 11 ms), one reused read-only connection per
   `Memory` instead of re-fingerprinting the database file on every call (11 -> 7 ms; 28 ms of every call on a 13k-unit store).

## 7. Experiments that were rejected (numbers measured, change not kept)

| experiment | measured | why rejected |
|---|---|---|
| IDF / N / average length from the authorized *population* (SQL counts) instead of the candidate set | A hit@10 0.6519 -> 0.6514 / 0.6493 / 0.6529 (three length variants), recall@10 +0.001..+0.003, C +0.001..+0.003, +1.5 ms | below the 0.005 bar; with OR discovery every unit containing a term is a candidate, so the document frequency is the same and only N differs |
| stopword list: none | A hit@10 0.6630 -> 0.6357 (-0.027), C -0.010, D +0.067 | worse on real data; D gains because first-person words bridge a template gap (an artifact of the synthetic text) |
| stopword list: extended (modal verbs, prepositions, ...) | A +0.0055, C +0.001, D -0.025 | not a clear win; regresses D by three questions |
| stopword list: shorter | A -0.016, D +0.017 | worse on real data |
| proximity bonus (query terms within 1, 3 or 5 tokens of each other) | best A hit@10 +0.0020, C -0.0005, D hit@1 +0.05 (only for adjacency with weight 1.0) | below the bar on real data; the D gain is a template artifact |
| session-level aggregation (rank sessions by max + lambda x the next two/five unit scores) | without neighbor propagation C hit@1 0.6796 -> 0.7064, MRR +0.019, hit@10 +0.0015; with it at best hit@10 0.9536 -> 0.9561 (+0.0025), MRR -0.0004 | redundant once neighbors are propagated; "sum of all units" is worse (hit@1 0.544) |
| rare-token weighting (IDF^p, p 0.6 .. 2.0) | p 1.25 / 1.5: A hit@10 -0.0005 / 0, B +0.007 / +0.006, C +0.004 / +0.001; p < 1 worse | below the bar; p 1 is already near optimum |
| AND-first when at least K candidates exist (K 5 .. 50) | LoCoMo A-C within 0.0005; no latency change on the document probes | no measurable effect, extra code |
| neighbor propagation as `max(own, 0.5 x neighbor)` (no reinforcement) | B hit@10 0.7699, hit@1 back to the no-neighbor value; document probe p@1 0.744 | loses the rank-1 and session-level gain; the coverage-aware form keeps both |
| neighbor propagation by unit kind (text only, text + heading) | document probe unchanged | the harm was in prose paragraphs, not tables |
| population-wide `bm25()` of FTS5 for discovery order | not run | would let rows outside the authorized scope influence which authorized rows survive a full window (section 8) |
| result-time context expansion (return neighbors next to each hit) | not implemented | does not change the ranked list, so no measurable hit@k effect; it adds a field to `RecallHit`, which T6b is wiring into the CLI and the MCP tools concurrently |
| recency tie-break for devlog | not implemented | no ground truth to measure it; ties still break by reference (older first) |

## 8. Authorization invariants

Scope filtering still happens before any ranking input is computed, and the new inputs are authorized-only:

* discovery, the candidate window and the coverage order are in the same SQL statement as the scope and metadata predicates;
* neighbors are read by `(source, position)` and pass through the same scope and metadata filter before they are scored;
* nothing uses FTS5 `bm25()` or any other statistic of the whole index;
* the Python scope check stays as the final filter, and `lexical_score` of a unit depends only on units the caller may read.

`tests/unit/test_t7_retrieval_authorization.py` compares, for several callers, queries and random multi-tenant corpora (multi-paragraph
sources included, tiny candidate windows included), the texts, scores and order returned by a store that also holds other principals'
rows with the ones returned by a store holding only the caller's authorized rows: they are identical (the 38 tests of that file), and no returned hit
ever belongs to another principal.

**Finding T7-F1 (fixed): hidden rows decided the AND/OR fallback.** The previous discovery ran the AND query over the *whole* FTS
index and applied the scope filter afterwards. If any row of another profile matched every term, the AND pass was non-empty, so the
OR fallback never ran for the caller, whose own partially-matching rows were then missing. The result for an authorized caller
therefore depended on whether unauthorized rows existed (an existence oracle for hidden content matching all query terms), and the
T3 tests (`test_hidden_candidates_do_not_shift_scores`) did not see it because they compared scores, not membership. RED before the
fix: 3 black-box membership cases (`caroline adoption`, `support group marathon library`) and 2 tiny-window cases; the discovery
cap had the same flaw (other profiles' rows filled the window; RED: 3 tests). Both are fixed by pushing the scope and metadata predicates into the
discovery SELECT.

`Memory.recall` now reuses one read-only connection while the derived database file is the same `(device, inode)`; a replaced file
is reopened, an error drops the connection, grants and new writes are read through the same connection on every call (revoke and
re-grant are effective on the very next recall, `tests/unit/test_t7_recall_connection.py`).

## 9. Scale, document queries and the cost of the OR design

A 13,293-unit store built by `Memory.ingest` from this repository's `docs/` tree (604 files; `limit` 8, a warm process):

| probe | engine | p@1 | p@8 | MRR | recall p50 / p95 |
|---|---|---|---|---|---|
| 195 keyword queries: 3, 4 or 6 random words of a unit (gold = that unit) | previous AND-first ranking | 0.841 | 0.974 | 0.895 | 0.8 / 4.4 ms |
| | final | 0.749 | 0.969 | 0.839 | 31 / 52 ms |
| 200 queries: the first 15 words of a unit (the T3 self-retrieval format) | previous | 0.985 | 1.000 | 0.990 | 2.3 / 5.4 ms |
| | final | 0.970 | 1.000 | 0.983 | 46 / 67 ms |

This is the honest cost of the change: on a large *document* store, exact keyword queries are answered 20-40x slower and
slightly less precisely than before (the previous AND-first ranking is close to ideal for "every word of the query is in the unit").
The ranking was tuned on conversational data (LoCoMo) and the document probe was added only as a regression check; the additive form
of neighbor propagation had lost 0.08 p@1 there before it was made coverage-aware. The latency is bounded by the 500-unit window
(it does not grow with the store beyond SQLite's postings scan) and is far below the cost of the LLM call that consumes the result,
but it is not the 1-5 ms of the previous ranking. A follow-up could choose the ranking per memory type (chat-like sources vs files);
that is not done here.

## 10. Honest limits

* **No real LongMemEval numbers.** Download of `longmemeval_s_cleaned.json` failed (HTTP 403 from the egress policy on
  `huggingface.co`). Section 4 D is a synthetic template-based set: it checks the session-level code path and ranks changes that
  affect word matching (stemming moved single-session-assistant hit@1 from 0.50 to 1.00), and it saturates at 0.8667 hit@10 because the remaining questions need meaning.
  Do not quote D as a LongMemEval result. `benchmarks/README.md` documents how to run the real file.
* **Lexical only.** No semantic or embedding matching, no query rewriting; "which novel" will never match "book". The optional
  `SemanticAdapter` hook in `retrieval.py` is untouched and unused.
* **Retrieval is not QA accuracy.** The official LoCoMo / LongMemEval metrics are LLM-judged answers; recall of the evidence is an
  upper-bound proxy.
* **Tuned on LoCoMo.** k1, b, the coordination exponent and the neighbor weight were chosen on LoCoMo (first half / second half
  validation, same direction on both halves) with 1,982 questions from 10 conversations of two speakers; expect smaller gains on other
  data. LoCoMo hit@10 differences below about 0.01 are within noise (standard error 0.010 on 1,982 questions, less for paired
  differences); that is why the bar was 0.005 for a change and 0.01 for a regression.
* **English only** stopwords and stemming. Vietnamese diacritic folding is kept; Vietnamese matching of tone-marked text still depends
  on the FTS tokenizer options of the derived store (T2 scope).
* **Large stores** answer slower than before (section 9); within-source duplicate units are still excluded at discovery.
* The coordination factor costs the session-level configuration 0.004 hit@10 (section 6).
* LoCoMo evidence ids that match no turn (9 questions) cap the turn-level recall slightly; the benchmark keeps them as the dataset has them.

## 11. Reproduce

```bash
curl -sS -o /tmp/locomo.json https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
python benchmarks/memory_qa_benchmark.py locomo /tmp/locomo.json -k 1 5 10 --check-determinism --json a.json                 # A
python benchmarks/memory_qa_benchmark.py locomo /tmp/locomo.json -k 1 5 10 --check-determinism --ingest session --json b.json  # B
python benchmarks/memory_qa_benchmark.py locomo /tmp/locomo.json -k 1 5 10 --check-determinism --level session --json c.json   # C
python benchmarks/synth_longmemeval.py --seed 7 --questions 120 --sessions 40 --out /tmp/synth_lme.json
python benchmarks/memory_qa_benchmark.py longmemeval /tmp/synth_lme.json -k 1 5 10 --check-determinism --json d.json            # D
```

Each run takes 40-80 s. The ranking fingerprints of the final code on this machine were
`67acb66a2455abe8` (A), `972f8f2058a3fb26` (B), `6ddd43ce16a38e80` (C), `48f39682b7ffc0f8` (D).
The baseline columns re-run with the `e66f0d8` ranking (`git show e66f0d8:src/corpus/retrieval.py`) and the retired store from
`git show 755b40b^:zero_mem/notes.py`; their scratch harnesses were not committed.
