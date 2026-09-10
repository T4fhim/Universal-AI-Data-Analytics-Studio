# File: uadas_core/services/__init__.py
"""Service layer: settings, project lifecycle, and workspace tracking.

Services in this package depend on ``uadas_core.core`` (for exceptions,
logging, and the ``AppConfig`` type) but ``uadas_core.core`` must never
depend back on this package at runtime — see
``uadas_core.core.application_state``'s module docstring for the specific
reasoning. This keeps the dependency direction consistent with the
project's layered architecture (Application -> Service -> Business
Logic -> Data -> Presentation -> Plugin).
"""
