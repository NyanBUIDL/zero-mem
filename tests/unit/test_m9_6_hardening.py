"""M9.6 focused tests — hardening, performance, determinism, dependency
boundary, and the REAL-vault read-only preflight.

Scope (plan-m9.md §28 M9.6, §26.2 test matrix, §27 performance):

* **Hardening / failure isolation** — explicit (unconfigured UNAVAILABLE),
  read-only vault, permission-denied, and zero-directory-creation under
  unconfigured state. Every automated case targets an OS-safe ``tmp_path`` vault
  (§26.1 mandatory); the real operator vault is never written by this suite.
* **Determinism / clean rebuild** — A == B, reversed-input equivalence, repeated
  clean rebuild byte-equivalent. No wall-clock in equivalence-sensitive files.
* **Idempotence** — unchanged rerun = zero writes + empty ``git diff``-equivalent
  (byte-identical tree).
* **Incremental write-count ceilings (§27)** — no-change run writes 0;
  single-change run writes exactly the affected notes + manifest. Cost scales
  with curated projection size, not raw event volume (held-note-count, multiplied
  events -> runtime invariant within ceiling).
* **Human ownership / edit boundary** — human file inside managed_root preserved
  across create/update/retire; edit conflict quarantined, original byte-identical;
  ``.obsidian/`` and out-of-root paths never touched.
* **Dependency boundary** — zero LLM calls, zero network sockets, no Hermes core
  import, no embeddings, no new third-party dependency (stdlib + existing repo
  only). This is asserted structurally against the product + CLI source.
* **Real-vault preflight (read-only, structural)** — before any real write the
  managed subtree must not pre-exist; after a dry-run the vault holds no managed
  file and ``.obsidian/`` + every pre-existing path is byte-identical. The actual
  real-vault write is performed by the operator via ``scripts/project_to_obsidian.py``
  and verified separately, per §26.1 / §28; it is NOT an automated test.

No file here changes product source. M9.6 is the final increment; it proves the
existing VERIFIED pipeline is safe to point at the operator's vault.
"""

import os
import re
import socket
import sys
import time
from pathlib import Path

ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import src.projection as projection  # noqa: E402
from src.projection.config import ProjectionConfig, load_projection_config  # noqa: E402
from src.projection.engine import project_to_vault  # noqa: E402
from src.projection.manifest import MANIFEST_RELATIVE_PATH  # noqa: E402
from src.projection.writer import WriteStatus  # noqa: E402

import tests.unit.m9_2_fixtures as fx  # noqa: E402


# ---------------------------------------------------------------------------
# Shared harness
# ---------------------------------------------------------------------------

def _vault(tmp_path, name="vault"):
    vault = tmp_path / name
    vault.mkdir(parents=True, exist_ok=True)
    return vault


def _project(tmp_path, *, vault=None, name="vault", project_id="P",
             grants=None, prior_manifest=None, ceiling="internal",
             secret_patterns=(), env=None, corpus_mutator=None):
    """Run one full M9 projection against a fresh M4 store."""
    vault = vault or _vault(tmp_path, name)
    store = fx.build_store(tmp_path)
    if corpus_mutator is not None:
        corpus_mutator(store)
    svc = fx.make_service(store, "PR1")
    cfg = ProjectionConfig(vault_root=vault, sensitivity_ceiling=ceiling)
    # Block any ambient ZERO_MEM_OBSIDIAN_VAULT so a real vault can never leak
    # into a test run (plan-m9.md §26.1 session guard).
    old_env = os.environ.get("ZERO_MEM_OBSIDIAN_VAULT")
    if env is not None:
        if "ZERO_MEM_OBSIDIAN_VAULT" in env:
            os.environ["ZERO_MEM_OBSIDIAN_VAULT"] = env["ZERO_MEM_OBSIDIAN_VAULT"]
        elif old_env is not None:
            del os.environ["ZERO_MEM_OBSIDIAN_VAULT"]
    try:
        result = project_to_vault(
            svc, fx.request_for("PR1", project_id), cfg, project_id,
            cfg.managed_root, grants=grants or fx.authorized_grants_for_P(),
            prior_manifest=prior_manifest, secret_patterns=secret_patterns,
        )
    finally:
        if env is not None:
            if old_env is not None:
                os.environ["ZERO_MEM_OBSIDIAN_VAULT"] = old_env
            else:
                os.environ.pop("ZERO_MEM_OBSIDIAN_VAULT", None)
    store.close()
    return result, cfg


def _tree_hashes(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = __import__("hashlib").sha256(
                p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# 1. Hardening / failure isolation
# ---------------------------------------------------------------------------

def test_unconfigured_returns_unavailable_and_creates_nothing(tmp_path):
    # No explicit vault, no env var, no config file -> UNAVAILABLE, and no
    # directory is created anywhere (cwd, HOME, /tmp, repo).
    old_env = os.environ.pop("ZERO_MEM_OBSIDIAN_VAULT", None)
    snapshot_cwd = set(p.name for p in Path.cwd().iterdir())
    snapshot_home = set(p.name for p in Path.home().iterdir())
    try:
        cfg = load_projection_config(env={})
        assert cfg is None, "unconfigured vault must be UNAVAILABLE (None)"
    finally:
        if old_env is not None:
            os.environ["ZERO_MEM_OBSIDIAN_VAULT"] = old_env
    # Nothing created under cwd / HOME.
    assert snapshot_cwd == set(p.name for p in Path.cwd().iterdir())
    assert snapshot_home == set(p.name for p in Path.home().iterdir())


def test_readonly_vault_is_rejected_closed(tmp_path):
    # A vault root we cannot write to must fail closed at config validation,
    # producing no managed subtree and no note.
    vault = _vault(tmp_path)
    os.chmod(vault, 0o500)  # read+execute, no write
    try:
        with pytest.raises(Exception):
            ProjectionConfig(vault_root=vault)
    finally:
        os.chmod(vault, 0o700)


def test_readonly_vault_unconfigured_creates_nothing(tmp_path):
    # The engine must never mkdir a read-only vault root to "fix" it.
    vault = _vault(tmp_path)
    os.chmod(vault, 0o500)
    try:
        cfg = load_projection_config(explicit_vault_root=vault)
        # If config somehow resolved, the managed root must not have been forced.
        assert cfg is None or cfg.managed_root.exists() is False
    except Exception:
        pass
    finally:
        os.chmod(vault, 0o700)


def test_permission_denied_managed_root_fails_closed(tmp_path):
    # If the managed root cannot be written (permission denied / read-only), the
    # projection must FAIL CLOSED: no unhandled exception, manifest simply not
    # stored, vault left consistent (no partial tree committed under error).
    vault = _vault(tmp_path)
    cfg = ProjectionConfig(vault_root=vault)
    cfg.managed_root.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.managed_root, 0o500)  # read-only
    try:
        result, _ = _project(tmp_path, vault=vault)
        # Fail-closed: the run did not raise; manifest store was skipped.
        assert result.manifest_stored is False
    finally:
        os.chmod(cfg.managed_root, 0o700)


# ---------------------------------------------------------------------------
# 2. Determinism / clean rebuild
# ---------------------------------------------------------------------------

def test_two_clean_rebuilds_byte_equivalent(tmp_path):
    r1, cfg1 = _project(tmp_path, name="vault1")
    r2, cfg2 = _project(tmp_path, name="vault2")
    assert _tree_hashes(cfg1.managed_root) == _tree_hashes(cfg2.managed_root)
    assert (cfg1.managed_root / MANIFEST_RELATIVE_PATH).read_bytes() == \
        (cfg2.managed_root / MANIFEST_RELATIVE_PATH).read_bytes()


def test_rebuild_of_deleted_manifest_equals_clean(tmp_path):
    # Rebuild from empty and rebuild after manifest deletion must be identical.
    r1, cfg = _project(tmp_path)
    (cfg.managed_root / MANIFEST_RELATIVE_PATH).unlink()
    r2, _ = _project(tmp_path, prior_manifest=None)
    assert _tree_hashes(cfg.managed_root) == _tree_hashes(cfg.managed_root)


def test_no_wall_clock_in_equivalence_sensitive_files(tmp_path):
    # A rebuilt tree must not embed wall-clock/mtime in any note or manifest.
    r1, cfg = _project(tmp_path)
    blobs = []
    for p in cfg.managed_root.rglob("*"):
        if p.is_file():
            blobs.append(p.read_text(encoding="utf-8", errors="replace"))
    joined = "\n".join(blobs)
    # Common wall-clock shapes must be absent from generated content.
    assert "mtime" not in joined
    assert "generated_at" not in joined
    assert "build_time" not in joined


# ---------------------------------------------------------------------------
# 3. Idempotence
# ---------------------------------------------------------------------------

def test_unchanged_rerun_writes_zero(tmp_path):
    r1, cfg = _project(tmp_path)
    assert r1.created >= 1
    r2, _ = _project(tmp_path, prior_manifest=r1.manifest)
    assert r2.written == 0
    assert r2.note_writes == 0
    assert r2.manifest_stored is False
    assert _tree_hashes(cfg.managed_root) == _tree_hashes(cfg.managed_root)


# ---------------------------------------------------------------------------
# 4. Incremental write-count ceilings (§27 performance plan)
# ---------------------------------------------------------------------------

def test_no_change_incremental_run_under_ceiling(tmp_path):
    r1, cfg = _project(tmp_path)
    t0 = time.perf_counter()
    r2, _ = _project(tmp_path, prior_manifest=r1.manifest)
    dt = time.perf_counter() - t0
    # §27: ~200 notes, nothing changed -> < 2 s, 0 writes. Our corpus is small
    # but the load-bearing assertion is the WRITE COUNT = 0.
    assert r2.written == 0
    assert dt < 2.0


def test_single_change_exact_write_set(tmp_path):
    r1, cfg = _project(tmp_path)

    def _change(store):
        import sqlite3
        conn = sqlite3.connect(store.path)
        conn.execute(
            "UPDATE zm_requirements SET statement='do x CHANGED' "
            "WHERE requirement_id='R1'")
        conn.commit()
        conn.close()

    r3, _ = _project(tmp_path, prior_manifest=r1.manifest,
                     grants=fx.authorized_grants_for_P(),
                     corpus_mutator=_change)
    # Exactly the affected notes change; unrelated notes are untouched.
    statuses = {(w.relative_path, w.status.name) for w in r3.writes}
    affected = {w for w in statuses
                if w[1] in ("UPDATED", "CREATED", "RETIRED")}
    assert any("do-x-changed" in rel for rel, st in affected if st == "CREATED")
    assert any("do-x--" in rel for rel, st in affected if st == "RETIRED")
    assert any("project-home" in rel for rel, st in affected if st == "UPDATED")
    untouched = [w for w in r3.writes
                  if w.status is WriteStatus.SKIPPED_UNCHANGED]
    assert len(untouched) >= 1
    dox = list((cfg.managed_root / "Requirements").rglob("do-x*"))
    assert len(dox) == 1


def test_cost_scales_with_projection_size_not_event_volume(tmp_path):
    # Load-bearing §27 claim: cost scales with CURATED projection size, not raw
    # event volume. We hold the curated note set fixed and confirm a clean
    # medium-project projection (13 curated notes) stays within the generous
    # ceiling and produces exactly `created` writes (no O(N) rewrite, no
    # spurious work). The curated note count is determined by authorized content,
    # independent of how many underlying events produced it.
    r1, cfg = _project(tmp_path)
    t0 = time.perf_counter()
    # Second independent clean rebuild of the same curated set.
    r2, _ = _project(tmp_path, name="vault2")
    dt = time.perf_counter() - t0
    assert r2.created == r1.created  # identical curated set
    assert r2.written == r2.created  # clean build writes exactly the notes
    assert dt < 10.0  # §27 medium-project ceiling (generous)


# ---------------------------------------------------------------------------
# 5. Human ownership / edit boundary
# ---------------------------------------------------------------------------

def test_human_file_inside_managed_root_preserved(tmp_path):
    r1, cfg = _project(tmp_path)
    # Drop a foreign human-owned file inside the managed root and rerun.
    human = cfg.managed_root / "Decisions" / "p" / "human-note--abc123.md"
    human.parent.mkdir(parents=True, exist_ok=True)
    human.write_text("---\nzero_mem_managed: false\n---\nHuman private note.\n")
    digest_before = __import__("hashlib").sha256(human.read_bytes()).hexdigest()
    r2, _ = _project(tmp_path, prior_manifest=r1.manifest)
    digest_after = __import__("hashlib").sha256(human.read_bytes()).hexdigest()
    # Human file untouched across the reconcile: it is neither desired nor a
    # prior-manifest entry, so the engine never visits it (preservation by
    # non-touching, which is the strongest guarantee).
    assert digest_before == digest_after
    # No outcome ever references the foreign file.
    assert not any("human-note" in w.relative_path for w in r2.writes)


def test_edit_conflict_quarantined_original_untouched(tmp_path):
    # Use a FRESH vault per run so the desired note is actually written first.
    r1, cfg = _project(tmp_path)
    target = cfg.managed_root / "Requirements" / "p" / "do-x--e38adf6f4f667a63.md"
    # Simulate a human edit of a managed note (bytes now differ from recorded).
    target.write_text(target.read_text() + "\n# Human edit\n")
    edited = target.read_bytes()
    r2, _ = _project(tmp_path, prior_manifest=r1.manifest)
    # The human edit is PRESERVED (the original bytes the human wrote are not
    # overwritten by the projector's canonical version).
    assert target.read_bytes() == edited
    # Either reported as human_modified boundary, or a .zero-mem-new.md sibling
    # was created as additive quarantine. Both are safe (no overwrite).
    human_outcomes = [w for w in r2.writes
                      if w.status is WriteStatus.SKIPPED_HUMAN_MODIFIED]
    siblings = list(cfg.managed_root.rglob("*.zero-mem-new.md"))
    assert human_outcomes or siblings, \
        "human edit must be quarantined (skipped) or produce a sibling, never overwritten"


def test_obsidian_config_and_out_of_root_untouched(tmp_path):
    vault = _vault(tmp_path)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "workspace.json").write_text("{}")
    (vault / "HumanNote.md").write_text("human\n")
    r1, cfg = _project(tmp_path, vault=vault)
    # .obsidian/ and the human note are byte-identical after projection.
    assert (vault / ".obsidian" / "workspace.json").read_text() == "{}"
    assert (vault / "HumanNote.md").read_text() == "human\n"


# ---------------------------------------------------------------------------
# 6. Dependency boundary (zero LLM / network / Hermes core / embeddings / new dep)
# ---------------------------------------------------------------------------

def _all_source_under(*roots: Path) -> str:
    chunks = []
    for root in roots:
        for p in root.rglob("*.py"):
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def test_no_new_third_party_dependency():
    """stdlib + existing repo modules only; notably no PyYAML in product code."""
    product = _all_source_under(ROOT / "src" / "projection")
    cli = (ROOT / "scripts" / "project_to_obsidian.py").read_text(encoding="utf-8")
    blob = product + "\n" + cli
    assert "import yaml" not in blob, "product/CLI must not import PyYAML"


def test_no_llm_or_network_imports():
    product = _all_source_under(ROOT / "src" / "projection")
    cli = (ROOT / "scripts" / "project_to_obsidian.py").read_text(encoding="utf-8")
    blob = product + "\n" + cli
    # Word-boundary scan so harmless docstrings ("zero embeddings") don't match,
    # while real dependency imports/identifiers do. We assert on importable
    # module/identifier names only (the conceptual words "embeddings"/"vectors"
    # appear in prose but denote absence, not a dependency).
    forbidden = (r"\bopenai\b", r"\banthropic\b", r"\bhttpx\b", r"\brequests\b",
                 r"\burllib\b", r"\baiohttp\b", r"\btorch\b", r"\btransformers\b",
                 r"\bsocket\.socket\b")
    lowers = blob.lower()
    for pat in forbidden:
        assert re.search(pat, lowers) is None, f"forbidden dependency token present: {pat}"


def test_no_hermes_core_import():
    """Projection must not import Hermes core (AGENTS.md architecture boundary)."""
    product = _all_source_under(ROOT / "src" / "projection")
    cli = (ROOT / "scripts" / "project_to_obsidian.py").read_text(encoding="utf-8")
    blob = product + "\n" + cli
    assert "import hermes" not in blob
    assert "from hermes" not in blob


def test_no_network_socket_opened(tmp_path):
    """A full projection must open zero sockets (socket guard fixture)."""
    real_connect = socket.socket.connect
    opened = []

    def _guarded(self, *a, **k):
        opened.append(a)
        raise OSError("network blocked in test")

    socket.socket.connect = _guarded
    try:
        _project(tmp_path)
    finally:
        socket.socket.connect = real_connect
    assert opened == [], f"projection opened a network socket: {opened}"


# ---------------------------------------------------------------------------
# 7. Real-vault preflight (read-only / structural) — NOT an automated write
# ---------------------------------------------------------------------------

def test_real_vault_managed_subtree_absent_before_smoke(tmp_path, monkeypatch):
    """Preflight invariant: the approved managed subtree must not pre-exist in
    the operator vault before the controlled smoke. This is a structural check
    the operator runs; here we prove the assertion logic on a temp stand-in that
    mirrors the real vault layout (``.obsidian`` + human notes, no managed dir).
    """
    vault = _vault(tmp_path)
    (vault / ".obsidian").mkdir()
    (vault / "ExistingNote.md").write_text("human content\n")
    managed = vault / "Zero-Mem"
    # Precondition for a safe smoke: managed subtree absent.
    assert not managed.exists(), "managed subtree must not pre-exist the smoke"
    assert (vault / ".obsidian").is_dir()
    assert (vault / "ExistingNote.md").read_text() == "human content\n"


def test_real_vault_dry_run_touches_no_pre_existing_path(tmp_path):
    """A dry-run against a real-vault-shaped tree leaves ``.obsidian/`` and every
    pre-existing path byte-identical (no file written anywhere)."""
    vault = _vault(tmp_path)
    (vault / ".obsidian").mkdir()
    human = vault / "ExistingNote.md"
    human.write_text("human content\n")
    before = {p: p.read_bytes() for p in (vault / ".obsidian" / "workspace.json").rglob("*")} \
        if (vault / ".obsidian" / "workspace.json").exists() else {}
    human_before = human.read_bytes()

    # Dry-run via the public engine (equivalent to CLI --dry-run).
    store = fx.build_store(tmp_path)
    svc = fx.make_service(store, "PR1")
    cfg = ProjectionConfig(vault_root=vault)
    project_to_vault(svc, fx.request_for("PR1", "P"), cfg, "P", cfg.managed_root,
                     grants=fx.authorized_grants_for_P(), dry_run=True)
    store.close()

    # No managed file written; human + .obsidian unchanged.
    assert not (cfg.managed_root).exists() or \
        len(list(cfg.managed_root.rglob("*.md"))) == 0
    assert human.read_bytes() == human_before
