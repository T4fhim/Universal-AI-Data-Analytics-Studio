# File: uadas_core/database/__init__.py
"""Live database connectivity: connection management and a query-result reader.

Milestone 14. Distinct in shape from :mod:`uadas_core.readers`,
:mod:`uadas_core.cleaning`, and :mod:`uadas_core.visualization`'s stateless
``Base*`` extension points: a database connection is inherently
stateful (it owns a live SQLAlchemy engine, the way
:class:`~uadas_core.ai.llm_provider.BaseLLMProvider` owns a live SDK client —
the one other package in this codebase already documented as the
deliberate exception to "stateless classmethod-only"), so
:class:`~uadas_core.database.base_connection.BaseDatabaseConnection` follows
that same instantiated-object shape rather than the classmethod-only
one. See that module's own docstring for the full reasoning, and
:mod:`uadas_core.database.database_reader` for why the reader built on top of
it does not itself subclass :class:`~uadas_core.readers.base_reader.
BaseReader`.
"""
