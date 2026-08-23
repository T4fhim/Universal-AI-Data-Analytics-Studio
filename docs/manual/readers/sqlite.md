---
title: "SQLite Reader"
anchors:
  - readers.sqlite
---

# SQLite Reader

`src.readers.sqlite_reader.SqliteReader` -- `.db`, `.sqlite`, `.sqlite3`.

Multi-table: a SQLite database file can contain any number of tables, each a candidate -- you
are asked which one to load if there is more than one.

## Dynamic typing

Unlike most SQL databases, SQLite does not strictly enforce a column's declared type -- a
column declared `INTEGER` can still hold a text value in a given row ("type affinity" rather
than strict typing). This is the same symptom (a column ending up with mixed value types) the
CSV reader's ambiguous-type detection already catches, so this reader reuses that same shared
check rather than re-implementing equivalent logic independently.

Table listing uses the standard library's `sqlite3` module directly (a lightweight
`sqlite_master` query), while the actual data read goes through `pandas.read_sql_query`.
