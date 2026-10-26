# File: tests/assets/test_design_reference_manifest.py
"""Structure guard for ``assets/design-reference/manifest.json`` (Phase 4 design references).

Why this exists: the manifest is the only in-repo record of the 29 design-reference
images, which are third-party screenshots deliberately kept *out* of git (decision 7 in
``plans/phase-4-design-reference.md``). If the file rots -- a role typo, a dropped entry,
an image committed by accident -- nothing else would notice. Like the ``ui-contract``
tests next to it, these assertions are a tripwire, not a feature test.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from uadas_core.core.constants import PROJECT_ROOT

REFERENCE_DIR = PROJECT_ROOT / "assets" / "design-reference"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Pinned at write time (2026-10-26). Changing these is allowed, but deliberately.
EXPECTED_FAMILY_COUNTS = {"A": 10, "B": 9, "C": 6, "D": 4}
EXPECTED_BASE_IDS = {"B4", "C6"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    path = REFERENCE_DIR / "manifest.json"
    assert path.is_file(), "assets/design-reference/manifest.json is missing"
    return json.loads(path.read_text(encoding="utf-8"))


def test_entry_count_and_family_split(manifest: dict) -> None:
    entries = manifest["entries"]
    assert len(entries) == 29
    assert Counter(e["family"] for e in entries) == EXPECTED_FAMILY_COUNTS


def test_ids_and_files_are_unique_and_well_formed(manifest: dict) -> None:
    entries = manifest["entries"]
    ids = [e["id"] for e in entries]
    files = [e["file"] for e in entries]
    assert len(set(ids)) == len(ids)
    assert len(set(files)) == len(files)
    for e in entries:
        assert re.fullmatch(r"[A-D]\d+", e["id"]), e["id"]
        assert e["id"][0] == e["family"], e["id"]
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), e["id"]
        width, height = e["size"]
        assert width > 0 and height > 0, e["id"]


def test_roles_follow_the_final_decision(manifest: dict) -> None:
    entries = manifest["entries"]
    assert {e["id"] for e in entries if e["role"] == "base"} == EXPECTED_BASE_IDS
    by_id = {e["id"]: e for e in entries}
    assert by_id["C6"]["authority"] == "final layout and theme"
    for e in entries:
        assert e["role"] in manifest["roles"], e["id"]
        if e["role"] == "skin":
            assert e["skin"] in {"phosphor", "editorial"}, e["id"]


def test_palette_values_are_hex_colours(manifest: dict) -> None:
    for e in manifest["entries"]:
        for name, value in e["palette"].items():
            assert HEX.match(value), f"{e['id']}.{name} = {value!r}"


def test_images_are_not_committed() -> None:
    """Decision 7: third-party screenshots stay local; only the manifest travels.

    Checks what git *tracks*, not what is on disk, so a developer may keep a local copy of the
    images here (``.gitignore`` hides them) without failing the suite.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")
    listing = subprocess.run(
        [git, "ls-files", "--", "assets/design-reference"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    stray = [f for f in listing if Path(f).suffix.lower() in IMAGE_SUFFIXES]
    assert stray == [], f"reference images must not be committed: {stray}"
