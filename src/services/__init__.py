# File: src/services/__init__.py
"""Service layer: settings, project lifecycle, and workspace tracking.

Services in this package depend on ``src.core`` (for exceptions,
logging, and the ``AppConfig`` type) but ``src.core`` must never
depend back on this package at runtime — see
``src.core.application_state``'s module docstring for the specific
reasoning. This keeps the dependency direction consistent with the
project's layered architecture (Application -> Service -> Business
Logic -> Data -> Presentation -> Plugin).
"""
