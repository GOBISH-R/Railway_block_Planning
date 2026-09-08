"""Frozen-artifact verification.

These tests exist so that an accidental edit to the frozen core or the frozen
dataset fails the suite loudly rather than being discovered later as an
unexplained change in a benchmark number.
"""
from __future__ import annotations

import hashlib
import os
import subprocess

import pytest

from blockplan_service import paths

FROZEN_UNDER_GIT = [
    "Dataset/blockplan/core.py",
    "Dataset/blockplan/pairing_rules.csv",
    "Dataset/blockplan-dataset/dataset/scenarios/method_comparison.csv",
    "Dataset/blockplan-dataset/dataset/scenarios/benchmark_results.csv",
]


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_core_py_is_byte_identical():
    """core.py's frozen identity. Every published number came from this file."""
    assert os.path.getsize(paths.CORE_PY) == paths.CORE_PY_BYTES
    assert _sha256(paths.CORE_PY) == paths.CORE_PY_SHA256


def test_core_py_still_uses_lf_endings():
    """Guards the byte count against a line-ending conversion.

    .gitattributes sets `* -text` precisely because core.autocrlf=true on this
    machine would otherwise rewrite core.py's 1,003 LF endings to CRLF on
    checkout, making it 45,047 bytes and silently invalidating every hash that
    refers to it.
    """
    with open(paths.CORE_PY, "rb") as f:
        data = f.read()
    assert data.count(b"\r\n") == 0, "core.py has CRLF endings; the freeze hash is broken"


@pytest.mark.parametrize("relative_path", FROZEN_UNDER_GIT)
def test_frozen_files_match_the_git_baseline(relative_path: str):
    """Byte-level comparison against the committed baseline."""
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", relative_path],
        cwd=paths.REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode == 128:
        pytest.skip("not a git repository")
    assert result.returncode == 0, (
        f"{relative_path} differs from the git baseline:\n{result.stdout}"
    )


def test_no_frozen_file_is_modified_in_the_working_tree():
    """Nothing anywhere under the frozen dataset tree may be dirty."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "Dataset/"],
        cwd=paths.REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("not a git repository")
    dirty = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert not dirty, "frozen tree has uncommitted modifications:\n" + "\n".join(dirty)


def test_benchmark_csv_still_holds_the_authoritative_b4_row():
    """The B4 row of record, kept deliberately despite the adapter correction.

    Settled 2026-09-06: this CSV row is authoritative, and the documentation
    was corrected to match it rather than the CSV being regenerated. The
    project memory's §22.1 B4 figures (142 / 259.8 / 79.9 / 35.9%) are
    superseded. Re-running the corrected adapter yields different B4 numbers
    (259.8 / 79.9) -- that divergence is known and accepted, not a reason to
    overwrite this file.
    """
    with open(paths.METHOD_COMPARISON_CSV, encoding="utf-8") as f:
        text = f.read()
    assert "B4 Bundle-only,138,175,0,272.8,1.6,69.0,54,0.391,0.99,0.74,0.403" in text
