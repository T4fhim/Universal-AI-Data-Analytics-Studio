---
title: "Connect to Database"
anchors:
  - data/connect-database
---

# Connect to Database

**File > Connect to Database...**.

Opens a live connection to a database server (or a local DuckDB file) and imports one table or
query result as a `Dataset` -- unlike every reader under
[Open Dataset](open-dataset.md), the source here is not a file that gets fully read once, but
a running connection `uadas_core.services.database_connection_service.DatabaseConnectionService`
tracks for the rest of the session.

## Supported databases

`uadas_core.database.connection_registry` maps a database type to its connector class:

- **PostgreSQL** (`postgres_connection.py`)
- **MySQL** (`mysql_connection.py`)
- **Microsoft SQL Server** (`sqlserver_connection.py`)
- **Oracle** (`oracle_connection.py`)
- **DuckDB** (`duckdb_connection.py`) -- an embedded, file-based analytical database; no
  separate server to connect to.

## Saved profiles vs. live connections -- and the password that is never saved

A **connection profile** (name, database type, host, port, database name, username) can be
saved and reappears in this dialog on future runs, via `config.yaml`'s `database.profiles` key.
The **password is never included** in a saved profile or written to `config.yaml` at all -- it
exists only in memory for the lifetime of the running process, alongside the live connection
object itself. Closing the application discards both. Reconnecting to a saved profile always
asks for the password again.

## Closing connections

Every connection opened this session is closed automatically when the application exits
(`DatabaseConnectionService.close_all_connections`) -- there is no separate "disconnect"
action required before quitting.
