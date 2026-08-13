# File: src/readers/type_inference.py
"""Shared column-level type-ambiguity detection, used by more than one reader.

:func:`find_ambiguous_type_columns` answers one question — "does this
column contain a mix of numeric and non-numeric values" — and is used
by both :class:`~src.readers.csv_reader.CsvReader` (where a mix
typically means a malformed or inconsistently-entered CSV column) and
:class:`~src.readers.sqlite_reader.SqliteReader` (where a mix is a
known, named SQLite behavior — "type affinity" — arising from SQLite
not strictly enforcing a column's declared type).

This function originated inside ``csv_reader.py`` and was extracted
here, rather than staying private to that module, when
``sqlite_reader.py`` needed the identical check: importing a
private, underscore-prefixed method across a module boundary
(``CsvReader._find_ambiguous_type_columns``) would have repeated a
private-import pattern already identified and fixed twice earlier in
this project (once for ``config.py``'s validation function in
milestone 1b-i, once by deliberately avoiding it for a sample-size
constant in milestone 2a's ``text_reader.py``). The fix here is the
same in kind: promote genuinely shared logic to a public, proper home
rather than reach into another module's internals.

The detection logic itself is unchanged from its original
implementation in ``CsvReader`` — see this function's own docstring
below for the two-round debugging history that shaped it, preserved
here rather than discarded, since it explains real, non-obvious
reasons the check works the way it does.
"""

from __future__ import annotations

import pandas as pd


def find_ambiguous_type_columns(dataframe: pd.DataFrame) -> list[str]:
    """Return names of columns containing a mix of numeric and non-numeric values.

    This function's implementation changed twice during milestone 2a's
    testing (originally as a method on
    :class:`~src.readers.csv_reader.CsvReader`), and the history is
    worth recording rather than silently overwriting, since it
    explains why the check works the way it does:

    1. The original version checked ``dtype == object``. Testing
       against this project's actual pandas version (3.0.2) found
       that ambiguously-typed columns come back as ``StringDtype``,
       not ``object``, in this pandas version — silently defeating the
       check entirely (it flagged nothing, ever, on this environment's
       pandas).
    2. The fix broadened the check to
       ``pd.api.types.is_string_dtype``. This correctly caught the
       real ambiguous-type case, but testing then found a new
       regression: pandas 3.0.2 uses ``StringDtype`` for *every* text
       column, not just ambiguous ones — so a genuinely all-text
       column (names, cities) started triggering the same warning as a
       genuinely ambiguous one, which is misleading and defeats this
       warning's purpose (flagging only what's actually notable).
    3. This version: rather than infer ambiguity from dtype at all
       (which testing showed is unreliable across pandas versions for
       this specific question), check content directly — a column is
       flagged only if it contains *some but not all* values that
       parse as numeric. A column with zero numeric-parseable values
       (genuinely all text) is not flagged. A column with all
       numeric-parseable values would already have been loaded with a
       numeric dtype by pandas and would not reach this function's
       text-dtype filter in the first place. Only the middle case — a
       mix — is flagged, which is the actually-ambiguous case this
       warning exists for.

    This still stops short of a dataset-profiling milestone's
    territory: it does not attempt to guess what the "correct" type
    should be, does not report what fraction of values were numeric,
    and does not distinguish different kinds of non-numeric values
    from each other. It answers exactly one question — "is there a
    mix, yes or no" — and leaves any further judgment to later
    milestones consuming a reader's ``read_warnings``.

    Args:
        dataframe: The DataFrame to inspect. Not mutated.
    """
    text_dtype_columns = [
        column_name
        for column_name, dtype in dataframe.dtypes.items()
        if dtype == object or pd.api.types.is_string_dtype(dtype)
    ]

    ambiguous_columns = []
    for column_name in text_dtype_columns:
        column = dataframe[column_name]
        numeric_parse_attempt = pd.to_numeric(column, errors="coerce")
        has_some_numeric = numeric_parse_attempt.notna().any()
        has_some_non_numeric = numeric_parse_attempt.isna().any()
        if has_some_numeric and has_some_non_numeric:
            ambiguous_columns.append(str(column_name))

    return ambiguous_columns
