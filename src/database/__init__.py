# File: src/database/__init__.py
"""Live database connectivity: connection management and a query-result reader.

Milestone 14. Distinct in shape from :mod:`src.readers`,
:mod:`src.cleaning`, and :mod:`src.visualization`'s stateless
``Base*`` extension points: a database connection is inherently
stateful (it owns a live SQLAlchemy engine, the way
:class:`~src.ai.llm_provider.BaseLLMProvider` owns a live SDK client —
the one other package in this codebase already documented as the
deliberate exception to "stateless classmethod-only"), so
:class:`~src.database.base_connection.BaseDatabaseConnection` follows
that same instantiated-object shape rather than the classmethod-only
one. See that module's own docstring for the full reasoning, and
:mod:`src.database.database_reader` for why the reader built on top of
it does not itself subclass :class:`~src.readers.base_reader.
BaseReader`.
"""
