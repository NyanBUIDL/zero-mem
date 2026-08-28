"""Executable v1.6.1 wheel/sdist license and metadata contract."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tests" / "packaging" / "check_release_artifacts.py"


def _artifacts(tmp_path: Path, *, include_sdist_notice: bool = True) -> tuple[Path, Path, Path, Path]:
    license_path = tmp_path / "LICENSE"
    notice_path = tmp_path / "NOTICE"
    license_path.write_bytes(b"MIT test license\n")
    notice_path.write_bytes(b"Research attribution test notice\n")

    wheel = tmp_path / "zero_mem-1.6.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        prefix = "zero_mem-1.6.1.dist-info"
        archive.writestr(f"{prefix}/licenses/LICENSE", license_path.read_bytes())
        archive.writestr(f"{prefix}/licenses/NOTICE", notice_path.read_bytes())
        archive.writestr(
            f"{prefix}/METADATA",
            "Metadata-Version: 2.4\nName: zero-mem\nVersion: 1.6.1\nAuthor: NyanBUIDL\n\n",
        )

    sdist = tmp_path / "zero_mem-1.6.1.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        entries = [("zero_mem-1.6.1/LICENSE", license_path.read_bytes())]
        if include_sdist_notice:
            entries.append(("zero_mem-1.6.1/NOTICE", notice_path.read_bytes()))
        for name, payload in entries:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return wheel, sdist, license_path, notice_path


def _run_checker(tmp_path: Path, *, include_sdist_notice: bool = True) -> subprocess.CompletedProcess[str]:
    wheel, sdist, license_path, notice_path = _artifacts(
        tmp_path, include_sdist_notice=include_sdist_notice
    )
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            str(wheel),
            str(sdist),
            "--expected-version",
            "1.6.1",
            "--expected-author",
            "NyanBUIDL",
            "--license",
            str(license_path),
            "--notice",
            str(notice_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_release_artifact_checker_accepts_matching_license_notice_and_metadata(tmp_path: Path) -> None:
    result = _run_checker(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "release_artifact_contract=PASS" in result.stdout


def test_release_artifact_checker_rejects_missing_sdist_notice(tmp_path: Path) -> None:
    result = _run_checker(tmp_path, include_sdist_notice=False)
    assert result.returncode != 0
    assert "NOTICE" in result.stderr
