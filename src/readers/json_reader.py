# File: src/readers/json_reader.py
"""Reads JSON files into a Dataset, handling both flat and nested structures.

JSON does not guarantee tabular structure the way a CSV file's rows
and columns do. This reader handles three shapes explicitly, in order
of how directly tabular they are:

1. **A JSON array of flat objects** — ``[{"a": 1, "b": 2}, ...]`` — the
   direct tabular case. Each object becomes a row, each key a column.
2. **A single JSON object with array-valued keys of equal length** —
   ``{"a": [1, 2, 3], "b": [4, 5, 6]}`` — the "columnar" JSON shape
   some tools export. Detected and handled as a second case rather
   than failing, since refusing to read a file that is genuinely
   tabular, just structured differently than case 1, would be an
   unnecessary limitation.
3. **A JSON array of *nested* objects** — objects containing objects or
   arrays as values — flattened via ``pandas.json_normalize``, which
   turns nested keys into dotted column names (``address.city``,
   ``address.zip``). This is a real, working case, not a rejection:
   nested JSON is common enough (API responses, exported records with
   sub-structures) that refusing to handle it would make this reader
   far less useful than it needs to be.

A JSON document that is none of the above (a single non-array,
non-columnar object; a deeply irregular array where objects have
wildly different shapes) is not silently forced into a table — this
reader raises :class:`~src.core.exceptions.ReaderError` with a message
describing what it found, rather than guessing at a tabular
interpretation of data that was never meant to be tabular.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_JSON_EXTENSIONS = {".json"}


class JsonReader(BaseReader):
    """Reads JSON files, handling flat arrays, columnar objects, and nested arrays.

    See the module docstring for the three shapes this reader
    recognizes. Every recognized shape is flattened into the same
    ``pandas.DataFrame`` structure every other reader in this package
    produces — nested-shape flattening is recorded as a warning (which
    columns were flattened from what nested path) so the user is aware
    the resulting column names don't match the original JSON keys
    one-to-one.
    """

    SUPPORTED_EXTENSIONS = _JSON_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _JSON_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read a JSON file at ``path``.

        Args:
            path: The file to read.
            table_name: Accepted for interface uniformity with
                :meth:`~src.readers.base_reader.BaseReader.read`, but
                ignored — a JSON file, as this reader interprets it,
                has exactly one table. See
                :meth:`~src.readers.csv_reader.CsvReader.read`'s
                docstring for the full reasoning, which applies
                identically here.

        Raises:
            ReaderError: If the file does not exist, is not valid
                JSON, or does not match any of the three recognized
                tabular shapes described in the module docstring.
        """
        if not path.exists():
            raise ReaderError(f"JSON file does not exist: {path}")

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ReaderError(
                f"JSON file {path} is not valid UTF-8. JSON files "
                f"must be UTF-8 encoded per the JSON specification."
            ) from exc

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ReaderError(f"File {path} is not valid JSON: {exc}") from exc

        warnings: list[str] = []
        dataframe = cls._to_dataframe(parsed, path, warnings)

        _logger.info(
            "Read JSON file %s: %d rows, %d columns, %d warning(s).",
            path,
            len(dataframe),
            len(dataframe.columns),
            len(warnings),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="json",
            source_path=path,
            read_warnings=warnings,
        )

    @classmethod
    def _to_dataframe(
        cls, parsed: Any, path: Path, warnings: list[str]
    ) -> pd.DataFrame:
        """Dispatch to the correct handling for whichever of the 3 shapes ``parsed`` is.

        Appends to ``warnings`` in place when nested-structure
        flattening occurs, rather than returning a separate value —
        kept as a single output (the DataFrame) with warnings
        collected as a side effect, matching how :class:`CsvReader`
        already threads warnings through its own private helpers.
        """
        if isinstance(parsed, list):
            return cls._handle_array(parsed, path, warnings)

        if isinstance(parsed, dict):
            if cls._is_columnar_shape(parsed):
                return pd.DataFrame(parsed)
            raise ReaderError(
                f"File {path} contains a single JSON object that is "
                f"not in columnar form (equal-length array values for "
                f"every key). A single non-columnar object has no "
                f"well-defined tabular interpretation — if this file "
                f"represents one record, consider wrapping it in an "
                f"array: [{{...}}]."
            )

        raise ReaderError(
            f"File {path} contains a top-level JSON value of type "
            f"{type(parsed).__name__}, which has no tabular "
            f"interpretation. Expected a JSON array or a columnar "
            f"object — see this reader's module docstring for the "
            f"three shapes it recognizes."
        )

    @classmethod
    def _handle_array(
        cls, items: list[Any], path: Path, warnings: list[str]
    ) -> pd.DataFrame:
        if len(items) == 0:
            raise ReaderError(f"File {path} contains an empty JSON array.")

        if not all(isinstance(item, dict) for item in items):
            raise ReaderError(
                f"File {path} contains a JSON array whose elements "
                f"are not all objects. Expected an array of objects "
                f"(one per row); found at least one element of a "
                f"different type."
            )

        has_nested_values = any(
            isinstance(value, (dict, list))
            for item in items
            for value in item.values()
        )

        if has_nested_values:
            dataframe = pd.json_normalize(items)
            warnings.append(
                "Some fields contained nested objects or arrays; "
                "these were flattened into dotted column names "
                "(e.g. 'address.city')."
            )
            cls._warn_about_null_shadow_columns(items, dataframe, warnings)
            return dataframe

        return pd.DataFrame(items)

    @classmethod
    def _warn_about_null_shadow_columns(
        cls, items: list[dict[str, Any]], dataframe: pd.DataFrame, warnings: list[str]
    ) -> None:
        """Warn about a known ``json_normalize`` edge case: redundant all-null columns.

        Found by adversarial testing during this milestone, not
        anticipated in advance: when the same field is a nested dict
        in some rows and ``null`` (or any non-dict value) in others,
        ``pandas.json_normalize`` produces *two* columns for that
        field — the flattened dotted-name column(s) from the rows
        where it was a dict, and a separate column under the field's
        original bare name holding the non-dict value (``NaN`` for a
        ``null``). For example, a field ``address`` that is
        ``{"city": "NYC"}`` in one row and ``null`` in another
        produces both an ``address.city`` column and a separate,
        entirely-``NaN`` ``address`` column — the latter contributing
        no information and likely confusing a user who did not expect
        it.

        This method does not attempt to fix the shape (dropping the
        shadow column, or otherwise reconciling it) — doing so would
        mean guessing at which columns are "meaningless" using
        content-based heuristics (an all-null column check), which is
        exactly the kind of judgment call this reader's design
        deliberately leaves to a later dataset-profiling milestone
        (see :meth:`CsvReader._find_ambiguous_type_columns`'s
        docstring for the same reasoning applied to a different
        heuristic question). Instead, this method only detects the
        situation and adds a warning naming the affected column, so
        the user is not left to discover an unexplained all-null
        column on their own.

        This method's first implementation had its own bug, found by
        testing it against a clean nested-data case immediately after
        writing it: it flagged ``name`` — an ordinary, never-nested,
        correctly-passed-through field — as a shadow column, because
        it checked whether *any* original field name appeared among
        the output columns. But a plain field like ``name`` is
        *supposed* to appear unchanged in the output; that is not the
        artifact this method exists to catch. The corrected check
        below only flags a field if it was a ``dict`` in at least one
        row (making it eligible to be flattened by
        ``json_normalize``) *and* its own bare name still appears as
        an output column (meaning some other row's value for that
        field was not a dict, so ``json_normalize`` could not flatten
        it and instead left it as a separate, disconnected column).
        """
        fields_nested_in_some_row = {
            key
            for item in items
            for key, value in item.items()
            if isinstance(value, dict)
        }
        dataframe_column_names = set(dataframe.columns)
        shadow_columns = sorted(
            fields_nested_in_some_row & dataframe_column_names
        )
        if shadow_columns:
            warnings.append(
                f"Column(s) {', '.join(shadow_columns)} may be "
                f"entirely empty: the same field was a nested "
                f"object in some rows and a plain value (e.g. null) "
                f"in others, which produces both a flattened column "
                f"and a separate, likely-empty column under the "
                f"original field name."
            )

    @classmethod
    def _is_columnar_shape(cls, obj: dict[str, Any]) -> bool:
        """Return whether ``obj`` matches shape 2: equal-length array values.

        An empty dict does not qualify (there are no columns to
        establish a row count from), and a dict where any value is
        not a list, or the lists are of unequal length, does not
        qualify either — both cases fall through to the "not
        columnar" error in :meth:`_to_dataframe` rather than this
        method guessing at a partial interpretation.
        """
        if not obj:
            return False
        if not all(isinstance(value, list) for value in obj.values()):
            return False
        lengths = {len(value) for value in obj.values()}
        return len(lengths) == 1
