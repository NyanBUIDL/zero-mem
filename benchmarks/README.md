# Benchmarks

Most scripts here are historical (M10, v1.3/v1.4 corpus work). The shared-memory retrieval benchmark is
`memory_qa_benchmark.py`; its results and the experiments behind the ranking are in
[`docs/benchmarks/RESULTS.md`](../docs/benchmarks/RESULTS.md).

## `memory_qa_benchmark.py` - retrieval quality over the real pipeline

Every haystack gets a fresh, private `zero_mem.memory.Memory` (temp data root, pinned profile `bench`), is filled through
the real write path (`Memory.add`: validation, authorization, secret pre-scan, registry, projection) and is queried through
the real authorized read path (`Memory.recall`). The script never touches the index directly. Zero LLM calls, no network,
deterministic.

It reports **hit@k**, **recall@k**, **MRR** (over the retrieved list, at most `--recall-limit` units), the same numbers per
question type, per-query `Memory.recall` **latency** (p50 / p95 / mean / max, ms), **ingest throughput** (adds per second
through the write path) and a `fingerprint` of every ranking. These are *retrieval* metrics against gold evidence; the official
LoCoMo and LongMemEval scores are LLM-judged answer accuracy and are not computed here.

### LoCoMo (turn level, session level)

```bash
curl -sS -o /tmp/locomo.json https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
python benchmarks/memory_qa_benchmark.py locomo /tmp/locomo.json -k 1 5 10                  # turn gold, one memory per turn
python benchmarks/memory_qa_benchmark.py locomo /tmp/locomo.json -k 1 5 10 --level session  # session gold, one memory per session
python benchmarks/memory_qa_benchmark.py locomo /tmp/locomo.json -k 1 5 10 --ingest session # turn gold, one memory per session
```

Gold is the `evidence` dia ids of each question (`--level turn`) or the sessions holding them (`--level session`, `Dn:m` ->
`session_n`). A full turn-level run writes about 5,900 memories and issues 1,982 recalls (about 70 s).

### LongMemEval

The files are hosted on HuggingFace (`xiaowu0162/longmemeval-cleaned`, `longmemeval_s_cleaned.json`,
`longmemeval_oracle.json`):

```bash
curl -sS -L -o /tmp/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
python benchmarks/memory_qa_benchmark.py longmemeval /tmp/longmemeval_s_cleaned.json -k 1 5 10 --limit 50 --seed 7
```

Gold is `answer_session_ids`; ranked items are distinct sessions. The default ingest is one memory per session (the
haystacks have about 50 sessions of about 10 turns each, so `--ingest turn` is roughly ten times slower). Use `--limit N`
(first N questions) or `--limit N --seed S` (a stable random sample of N) for a quick run.

**If HuggingFace is not reachable** (the sandbox that produced `RESULTS.md` could not reach it) generate a *synthetic* file
in the same format and say so wherever you quote numbers from it:

```bash
python benchmarks/synth_longmemeval.py --seed 7 --questions 120 --sessions 40 --out /tmp/synth_lme.json
python benchmarks/memory_qa_benchmark.py longmemeval /tmp/synth_lme.json -k 1 5 10
```

The generator is template based and a pure function of its arguments; numbers on it are **not** LongMemEval numbers (see
`docs/benchmarks/RESULTS.md`, "Honest limits").

### Determinism, seeds, output

| Option | Meaning |
|---|---|
| `--check-determinism` | query every question twice on the same store; exit status 3 if any ranking differs |
| `--seed S` | with `--limit N`: a stable random sample of N questions/conversations instead of the first N |
| `--json out.json` | also write the report to a file (the same JSON is printed on stdout) |
| `--level turn\|session` | gold granularity (default: turn for locomo, session for longmemeval) |
| `--ingest turn\|session` | one memory per turn or per session (default: by level) |
| `--recall-limit N` | units requested per query (1..200; default 40 per-turn ingest, 200 per-session) |
| `--cache-dir DIR` | keep the filled stores and reuse them: for ranking experiments only (ingest throughput is then not measured; delete the directory after touching anything on the write/projection path) |

Two runs with the same inputs and code print the same `fingerprint`; compare it across machines or commits to prove that a
refactor did not change a ranking. Latency numbers are wall-clock and depend on the machine (run on an otherwise idle
machine, do not use `--cache-dir` runs in parallel for latency).

### Tests

`tests/unit/test_t7_benchmark.py`, `tests/unit/test_t5_benchmark_memory_qa.py`, `tests/unit/test_t7_synth_longmemeval.py`.
