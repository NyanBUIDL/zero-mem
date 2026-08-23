"""V132-06 — master spec .docx freeze hash (D-03 Option A) unit tests.

Contract:
  * real repo: live .docx sha256 == anchor in ADR-V132-02;
  * fail-closed: tampered docx copy / missing anchor / missing ADR -> drift.
No content of the real .docx or MASTER-SPEC.md is modified.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "check_master_spec_hash",
    REPO_ROOT / "scripts" / "check_master_spec_hash.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

ADR_DIR = Path("docs/v1.3.2/decisions")


class TestV132Wp6MasterSpecFreeze:
    def test_real_repo_docx_matches_anchor(self):
        live, anchored = mod.check_master_spec(REPO_ROOT)
        assert anchored is not None
        assert live == anchored

    def test_tampered_copy_fails_closed(self, tmp_path):
        # Copy the real tree's docx into a fixture repo and flip one byte.
        src = REPO_ROOT / mod.DOCX_NAME
        dst = tmp_path / mod.DOCX_NAME
        data = bytearray(src.read_bytes())
        data[-1] ^= 0x01
        dst.write_bytes(bytes(data))
        (tmp_path / ADR_DIR).mkdir(parents=True)
        shutil.copy(REPO_ROOT / mod.ADR_REL, tmp_path / mod.ADR_REL)
        live, anchored = mod.check_master_spec(tmp_path)
        assert live != anchored
        # main() must exit non-zero on this drift.
        code = mod.main(["--repo", str(tmp_path)])
        assert code != 0

    def test_missing_anchor_fails_closed(self, tmp_path):
        shutil.copy(REPO_ROOT / mod.DOCX_NAME, tmp_path / mod.DOCX_NAME)
        live, anchored = mod.check_master_spec(tmp_path)
        assert anchored is None
        code = mod.main(["--repo", str(tmp_path)])
        assert code == 1

    def test_missing_docx_errors(self, tmp_path):
        code = mod.main(["--repo", str(tmp_path)])
        assert code == 1
