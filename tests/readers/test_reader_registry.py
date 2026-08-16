# File: tests/readers/test_reader_registry.py
"""Tests for src.readers.reader_registry.get_reader_for_path.

Covers a passing case for every registered reader's extension, the
ReaderError raised for an unsupported extension, and the mutual
exclusivity of SUPPORTED_EXTENSIONS across all registered readers —
reader_registry.py's own comment notes ordering only matters "when
more than one could theoretically claim a file," an assumption of
non-overlap that is not otherwise enforced in code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.exceptions import ReaderError
from src.readers.reader_registry import _REGISTERED_READERS, get_reader_for_path


@pytest.mark.parametrize("reader_class", _REGISTERED_READERS)
def test_get_reader_for_path_matches_each_registered_readers_extension(
    reader_class,
) -> None:
    for extension in reader_class.SUPPORTED_EXTENSIONS:
        path = Path(f"some_file{extension}")
        assert get_reader_for_path(path) is reader_class


def test_get_reader_for_path_raises_reader_error_for_unsupported_extension() -> None:
    with pytest.raises(ReaderError):
        get_reader_for_path(Path("some_file.not_a_real_extension"))


def test_no_two_registered_readers_claim_the_same_extension() -> None:
    seen: dict[str, type] = {}
    for reader_class in _REGISTERED_READERS:
        for extension in reader_class.SUPPORTED_EXTENSIONS:
            assert extension not in seen, (
                f"Extension '{extension}' is claimed by both "
                f"{seen.get(extension)} and {reader_class} — "
                f"reader_registry.py's ordering-dependent dispatch "
                f"assumes mutual exclusivity."
            )
            seen[extension] = reader_class
