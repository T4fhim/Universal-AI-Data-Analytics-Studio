# File: src/core/bootstrap.py
"""Application startup orchestration.

:func:`bootstrap` runs the fixed sequence every application startup
must follow, in the only order that avoids circular initialization:

1. Load configuration (``config.py`` does not depend on the logger —
   see the module docstring in ``config.py`` for why).
2. Configure logging, using the log settings just loaded from config.
   Nothing before this point may use :func:`~src.core.logger.get_logger`
   and expect file rotation or the application's log format; anything
   after this point may.
3. Construct the dependency container and register ``AppConfig`` and
   ``ApplicationState``.
4. Construct ``SettingsService``, ``ProjectService``, and
   ``WorkspaceService`` (introduced in milestone 1b-i) and register
   each into the same container. These are registered here — one
   instance per running process — rather than constructed directly
   inside UI code (milestone 1b-ii's ``main_window.py`` and its
   dialogs), so that every consumer resolves the same instance instead
   of each constructing its own and silently diverging (for example,
   two independent "recent projects" lists that don't know about each
   other).

The result is a :class:`BootstrapContext` — a small, immutable bundle
handed to :mod:`src.core.app`, which is the only other module that
should call :func:`bootstrap`. Nothing downstream of ``app.py`` should
need to call this function directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.application_state import ApplicationState
from src.core.config import AppConfig
from src.core.constants import CONFIG_FILE_PATH, LOG_DIR
from src.core.dependency_container import DependencyContainer
from src.core.exceptions import BootstrapError
from src.core.logger import configure_logging, get_logger
from src.services.analysis_orchestrator_service import AnalysisOrchestratorService
from src.services.project_service import ProjectService
from src.services.settings_service import SettingsService
from src.services.workspace_service import WorkspaceService


@dataclass(frozen=True)
class BootstrapContext:
    """Everything :mod:`src.core.app` needs after a successful bootstrap.

    Attributes:
        config: The loaded, typed application configuration.
        container: The dependency container, already populated with
            every service the application provides as of this
            milestone (``AppConfig``, ``ApplicationState``,
            ``SettingsService``, ``ProjectService``,
            ``WorkspaceService``). Later milestones register
            additional services into this same instance rather than
            constructing a new container.
        state: The session's :class:`~src.core.application_state.
            ApplicationState` instance. Also available via
            ``container.resolve(ApplicationState)`` — exposed
            directly here as well since ``app.py`` needs it
            immediately and resolving it through the container for
            that one access would add a layer of indirection with no
            benefit at the one call site that always needs it.
    """

    config: AppConfig
    container: DependencyContainer
    state: ApplicationState


def bootstrap(
    config_path: Path = CONFIG_FILE_PATH, log_dir: Path = LOG_DIR
) -> BootstrapContext:
    """Run application startup and return a ready-to-use context.

    Args:
        config_path: Location of the YAML configuration file. Defaults
            to the project's standard config location; overridable
            primarily for tests that want an isolated config file.
        log_dir: Directory rotating log files are written into.
            Defaults to the project's standard log location; same
            override rationale as ``config_path``.

    Returns:
        A populated :class:`BootstrapContext`.

    Raises:
        ConfigError: If configuration cannot be loaded or is invalid.
            Propagates from :meth:`AppConfig.load` unchanged, since it
            is already a specific, actionable
            :class:`~src.core.exceptions.ApplicationError` subclass.
        BootstrapError: If a startup step completes but produces a
            result a later step cannot use. Config and logging
            failures raise their own more specific exception types
            instead (see above); this is reserved for genuine
            sequencing failures in this function itself.
    """
    # Step 1: configuration. Must happen before logging is configured,
    # since logger.py needs the log level and rotation settings this
    # step produces.
    config = AppConfig.load(config_path)

    # Step 2: logging. Must happen before anything below this line
    # calls get_logger() and expects a properly formatted, rotating
    # log rather than Python's bare last-resort stderr handler.
    configure_logging(
        level=config.log_level,
        log_dir=log_dir,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
    )
    logger = get_logger(__name__)
    logger.info("Starting %s bootstrap sequence.", "application")

    # Step 3: dependency container. Constructed after logging so that
    # registration events (logged at DEBUG in dependency_container.py)
    # go through the fully configured logger rather than the bare
    # fallback handler.
    container = DependencyContainer()
    container.register(AppConfig, lambda: config, singleton=True)
    logger.debug("Registered AppConfig into the dependency container.")

    # Step 4: application state. Constructed last among this
    # milestone's services since it depends on nothing else here, but
    # is registered into the same container as everything else so
    # later milestones resolve it the same way they resolve any other
    # service.
    state = ApplicationState()
    container.register(ApplicationState, lambda: state, singleton=True)
    logger.debug("Registered ApplicationState into the dependency container.")

    # Step 5: milestone 1b-i's services. Constructed after
    # ApplicationState for consistency with the "core services first"
    # ordering above, though none of these three currently depend on
    # ApplicationState directly. ProjectService is seeded with
    # config.recent_projects so a freshly booted session remembers
    # projects opened in a previous run, rather than starting with an
    # empty recent-projects list every time despite config.yaml
    # already tracking one.
    settings_service = SettingsService(config, config_path)
    container.register(SettingsService, lambda: settings_service, singleton=True)
    logger.debug("Registered SettingsService into the dependency container.")

    project_service = ProjectService(recent_projects=config.recent_projects)
    container.register(ProjectService, lambda: project_service, singleton=True)
    logger.debug("Registered ProjectService into the dependency container.")

    workspace_service = WorkspaceService()
    container.register(WorkspaceService, lambda: workspace_service, singleton=True)
    logger.debug("Registered WorkspaceService into the dependency container.")

    # Milestone 9: depends on the WorkspaceService instance just
    # registered above (resolves/mutates datasets and visualizations
    # through it, exactly as AssistantService does) — registered after
    # it for the same "construct in dependency order" reasoning this
    # function already documents for every service above.
    analysis_orchestrator_service = AnalysisOrchestratorService(workspace_service)
    container.register(
        AnalysisOrchestratorService,
        lambda: analysis_orchestrator_service,
        singleton=True,
    )
    logger.debug(
        "Registered AnalysisOrchestratorService into the dependency container."
    )

    context = BootstrapContext(config=config, container=container, state=state)

    if context.config is None or context.container is None or context.state is None:
        # Defensive check: should be unreachable given the assignments
        # above, but guards against a future edit to this function
        # accidentally constructing BootstrapContext from a step that
        # silently returned an unusable value.
        raise BootstrapError(
            "Bootstrap sequence completed but produced an incomplete "
            "context. This indicates a bug in bootstrap() itself."
        )

    logger.info("Bootstrap sequence complete.")
    return context
