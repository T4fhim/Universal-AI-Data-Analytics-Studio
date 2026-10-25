# File: uadas_core/bootstrap.py
"""Application startup orchestration: a process half and a session half.

Startup is split along the line that decides whether one process can serve many
users (Phase 3 core session seam; plans/phase-3-session-seam.md):

* :func:`bootstrap_process` builds the **process-wide, tenant-free** world once:
  configuration, logging, the built-in registries, the
  :class:`~uadas_core.jobs.job_runner.JobRunner`, and the stateless
  :class:`~uadas_core.persistence.persistence_service.PersistenceService`. It returns
  a :class:`ProcessContext` whose container is the *parent* of every session.
* :func:`build_session` builds the **stateful per-user** services -- ``ApplicationState``,
  ``SettingsService``, ``ProjectService``, ``WorkspaceService``,
  ``AnalysisOrchestratorService``, ``GuidanceService``, ``ReportService`` and
  ``DatabaseConnectionService`` -- into a fresh *child*
  :class:`~uadas_core.core.dependency_container.DependencyContainer`. Two sessions share
  no mutable service state; dropping a session drops its services.
* :func:`bootstrap` is the legacy desktop entry point and stays exactly what it was:
  it composes the two (one process, one session) and returns the same
  :class:`BootstrapContext`.

``server_mode=True`` is the server half of plan 3.8. It makes the desktop-shaped
behaviours *impossible*, not merely unused: plugins are never loaded (the plugin
package is not even imported), no YAML file is read or written, logging goes to stderr
with no rotating files, and the process-global default-job-runner bridge is not
installed. See :func:`bootstrap_process` for the exact guarantees.

The fixed order inside :func:`bootstrap_process` is the only one that avoids circular
initialization (the same sequence ``bootstrap()`` always followed):

1. Load configuration (``config.py`` does not depend on the logger -- see the module
   docstring in ``config.py`` for why).
2. Configure logging, using the log settings just loaded from config. Nothing before
   this point may use :func:`~uadas_core.core.logger.get_logger` and expect file
   rotation or the application's log format; anything after this point may.
3. Construct the process dependency container and register ``AppConfig``.
4. Populate the built-in registries, *then* (desktop mode only) load plugins, which
   register into those same registries.
5. Construct the job runner and the persistence service.

``src.app`` (the Qt shell) was the only other caller of :func:`bootstrap`; it is
gone, and nothing downstream should need to call these functions directly -- the
Phase 3 API reaches them through ``uadas_api.core_bridge``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from uadas_core.cleaning import operation_registry
from uadas_core.core import constants
from uadas_core.core.application_state import ApplicationState
from uadas_core.core.config import AppConfig
from uadas_core.core.dependency_container import DependencyContainer
from uadas_core.core.exceptions import BootstrapError
from uadas_core.core.logger import configure_logging, get_logger
from uadas_core.core.process_mode import ProcessMode, claim_process_mode
from uadas_core.jobs import set_default_job_runner
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.jobs.thread_pool_executor_job_runner import ThreadPoolExecutorJobRunner
from uadas_core.persistence.persistence_service import PersistenceService
from uadas_core.results import result_renderer_registry
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
)
from uadas_core.services.database_connection_service import DatabaseConnectionService
from uadas_core.services.guidance_service import GuidanceService
from uadas_core.services.project_service import ProjectService
from uadas_core.services.report_service import ReportService
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService
from uadas_core.visualization import chart_registry

# Worker threads in the process-wide job runner. Unchanged from the single-session
# desktop value; a server sizes concurrency at the deployment layer (3.5), not here.
_JOB_RUNNER_MAX_WORKERS = 4


@dataclass(frozen=True)
class BootstrapContext:
    """Everything ``src.app`` needs after a successful bootstrap.

    Attributes:
        config: The loaded, typed application configuration.
        container: The dependency container, already populated with
            every service the application provides as of this
            milestone (``AppConfig``, ``ApplicationState``,
            ``SettingsService``, ``ProjectService``,
            ``WorkspaceService``). Later milestones register
            additional services into this same instance rather than
            constructing a new container. Since the session seam this is
            the *session* (child) container of the one process
            :func:`bootstrap` builds: it resolves its own per-user services
            and falls back to the process container for the rest, so every
            key it ever resolved still resolves.
        state: The session's :class:`~uadas_core.core.application_state.
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


@dataclass(frozen=True)
class ProcessContext:
    """The process-wide, tenant-free half of startup (see :func:`bootstrap_process`).

    Hold one per process and call :func:`build_session` once per user/request. It
    carries no per-user state, which is why one instance can safely back many sessions.

    Attributes:
        config: The process configuration. In server mode it has been normalised:
            plugins off, and no desktop ``recent_projects`` / saved database profiles
            (those would otherwise be shared by every tenant).
        container: The process container -- the *parent* of every session container.
            Holds ``AppConfig``, ``JobRunner``, ``PersistenceService`` and (desktop mode
            only) ``PluginManager``.
        job_runner: The process's job runner, exposed as a public attribute so callers
            that must not import :mod:`uadas_core.jobs` (the Phase 3 API) can still hand
            it on. Sessions also resolve it through ``container``.
        server_mode: Whether this process was started in server mode.
        config_path: Where each session's :class:`SettingsService` persists, or
            ``None`` (server mode) for purely in-memory settings.
    """

    config: AppConfig
    container: DependencyContainer
    job_runner: JobRunner
    server_mode: bool
    config_path: Path | None

    def close(self) -> None:
        """Release process resources (the job runner's idle worker threads).

        Safe to call more than once. Not called by the legacy :func:`bootstrap`, whose
        process lives as long as the interpreter, matching its old behaviour.
        """
        shutdown = getattr(self.job_runner, "shutdown", None)
        if callable(shutdown):
            shutdown(wait=False)


def _server_mode_config(config: AppConfig) -> AppConfig:
    """Return ``config`` normalised for a multi-tenant process (the argument is untouched).

    Plugins are forced off -- belt and braces, since server mode never constructs a
    ``PluginManager`` anyway, but it keeps ``process.config`` and every session's
    ``SettingsService`` truthful about it. ``recent_projects`` and saved database
    profiles are desktop-user state that would otherwise be *seeded into every
    tenant's* session, so they are emptied.
    """
    data = config.to_dict()
    data["plugins"]["enabled"] = False
    data["plugins"]["search_paths"] = []
    data["recent_projects"] = []
    data["database"]["profiles"] = []
    return AppConfig.from_dict(data)


def bootstrap_process(
    *,
    server_mode: bool = False,
    config: AppConfig | None = None,
    config_path: Path | None = None,
    log_dir: Path | None = None,
) -> ProcessContext:
    """Build the process-wide, tenant-free world and return it as a :class:`ProcessContext`.

    Args:
        server_mode: ``False`` (default) reproduces the desktop startup: YAML config,
            rotating log files, plugin loading. ``True`` is the multi-tenant server
            startup, whose guarantees are:

            * **Plugins are never loaded.** ``uadas_core.plugins`` is not imported, no
              ``PluginManager`` is constructed or registered, ``sys.path`` is not
              touched and the plugin registries are not written to.
            * **No YAML read or write.** Configuration comes only from ``config`` (or
              the in-code defaults); sessions get in-memory ``SettingsService`` objects.
            * **No log files, and the host's logging is not rewritten.** Logging goes
              to stderr through a handler on the ``uadas_core`` logger only
              (``propagate=False``); the root logger is never touched and no log
              directory is created.
            * **The mode is a one-way latch.** A process that has bootstrapped in
              server mode refuses every desktop entry point (:func:`bootstrap` and
              ``bootstrap_process(server_mode=False)``) and vice versa, so the
              guarantees cannot be undone -- or inherited the wrong way round --
              later in the same process.
            * **No process-global job-runner bridge.** ``set_default_job_runner`` is
              never called; sessions obtain the runner through the container.
            * **No ``PROJECT_ROOT`` dependence** for anything it does (fixed *data* paths
              honour ``UADAS_DATA_ROOT``, see :mod:`uadas_core.core.constants`).
        config: An already-built configuration. Required in spirit for a server (the
            caller builds it from its own settings/environment); ``None`` means "the
            in-code defaults" in server mode and "load ``config_path``" in desktop mode.
        config_path: Desktop only: the YAML file to load and that sessions persist
            settings to. Defaults to ``<data root>/config/config.yaml``.
        log_dir: Desktop only: where rotating log files go. Defaults to
            ``<data root>/logs``.

    Raises:
        BootstrapError: If ``server_mode`` is combined with ``config_path`` or
            ``log_dir`` -- both are file-backed, which server mode forbids -- or if
            this process already bootstrapped in the *other* mode (see the latch
            above; raised before any file is read or written).
        ConfigError: If desktop configuration cannot be loaded or is invalid
            (propagates from :meth:`AppConfig.load` unchanged -- it is already a
            specific, actionable :class:`~uadas_core.core.exceptions.ApplicationError`).
    """
    if server_mode and (config_path is not None or log_dir is not None):
        raise BootstrapError(
            "server_mode forbids config_path and log_dir: server mode reads and "
            "writes no YAML and creates no log files. Pass an AppConfig instead."
        )

    # One-way latch: a process is desktop or server, never both (see
    # uadas_core.core.process_mode). Claimed before any I/O so a refused call has no
    # side effects -- no config file written, no log directory created.
    claim_process_mode(ProcessMode.SERVER if server_mode else ProcessMode.DESKTOP)

    # Step 1: configuration. Must happen before logging is configured,
    # since logger.py needs the log level and rotation settings this
    # step produces.
    resolved_config_path: Path | None
    if server_mode:
        resolved_config_path = None
        config = _server_mode_config(
            config if config is not None else AppConfig.defaults()
        )
    else:
        resolved_config_path = (
            config_path if config_path is not None else constants.config_file_path()
        )
        if config is None:
            config = AppConfig.load(resolved_config_path)

    # Step 2: logging. Must happen before anything below this line
    # calls get_logger() and expects a properly formatted, rotating
    # log rather than Python's bare last-resort stderr handler. Server mode
    # logs to stderr only (no rotating files, no log directory) and attaches its
    # handler to the ``uadas_core`` logger, leaving the host's root logger alone.
    if server_mode:
        configure_logging(level=config.log_level, server_mode=True)
    else:
        configure_logging(
            level=config.log_level,
            log_dir=log_dir if log_dir is not None else constants.log_dir(),
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
    resolved = config
    container.register(AppConfig, lambda: resolved, singleton=True)
    logger.debug("Registered AppConfig into the dependency container.")

    # Web-transition 1.3: populate the built-in cleaning operations / chart types
    # / result renderers here rather than as a module-import side effect of their
    # registry modules (plans/phase-1-3-startup-graph.md §9). Each
    # _register_builtins() is idempotent. Must run before plugin loading
    # below, which registers plugin-provided operations and chart types into
    # these same registries. After startup the registries are read-only, which
    # is what makes them safe to share between sessions.
    operation_registry._register_builtins()
    chart_registry._register_builtins()
    result_renderer_registry._register_builtins()
    logger.debug(
        "Registered built-in cleaning operations, chart types, and result renderers."
    )

    # Milestone 12: constructed and loaded here — plugins should be
    # discovered and registered before anything in the UI layer (the
    # chart-builder dialog, the AI tool registry) first reads from the
    # shared chart/operation/reader registries those plugins register
    # into, so a plugin's classes are available from the very first
    # frame rather than appearing only after a later manual reload.
    # load_plugins() never raises for an individual plugin's own
    # problems (see plugin_loader.py's own docstring for why) — a bad
    # plugin is recorded on the PluginManager's loaded-plugin list for
    # a settings panel to surface, not a BootstrapError.
    #
    # Plugins are process-wide, not per-session: they mutate global registries
    # and sys.path, which is exactly why server mode refuses them outright. The
    # import is deferred INTO this branch so that, in server mode, the plugin
    # package is never even imported -- not merely never invoked (a test proves
    # it in a fresh interpreter). import-linter still counts a function-level
    # import, which is why .importlinter carries a narrow ignore for this edge.
    if not server_mode:
        from uadas_core.plugins.plugin_manager import PluginManager

        plugin_manager = PluginManager(
            search_paths=config.plugin_search_paths,
            enabled=config.plugins_enabled,
            disabled_plugin_names=set(config.plugin_disabled_names),
        )
        plugin_manager.load_plugins()
        container.register(PluginManager, lambda: plugin_manager, singleton=True)
        logger.debug("Registered PluginManager into the dependency container.")

    # Web-transition Phase 1.2: the Qt-free background-job runner. Registered
    # after plugin loading (plans/phase-1-2-jobrunner-design.md section 4) so a
    # plugin cannot resolve it mid-load before it exists, matching the
    # "construct in dependency order" reasoning used throughout this function.
    #
    # It is process-wide: one shared pool, stateless between jobs. The
    # set_default_job_runner() bridge for the disposable desktop BaseWorker is NOT
    # installed here -- only the legacy bootstrap() does that, so server-mode code
    # can only ever obtain the runner through the container (or
    # ProcessContext.job_runner), never through a process global.
    job_runner = ThreadPoolExecutorJobRunner(max_workers=_JOB_RUNNER_MAX_WORKERS)
    container.register(JobRunner, lambda: job_runner, singleton=True)
    logger.debug("Registered JobRunner into the dependency container.")

    # Web-transition Phase 1.6: the Qt-free workspace persistence layer
    # (plans/phase-1-6-persistence-contract.md §5). Stateless -- its storage
    # base is a per-call argument, so it has no constructor dependencies and is
    # safely process-wide: registered as a bare singleton.
    container.register(PersistenceService, lambda: PersistenceService(), singleton=True)
    logger.debug("Registered PersistenceService into the dependency container.")

    logger.info("Process bootstrap complete (server_mode=%s).", server_mode)
    return ProcessContext(
        config=config,
        container=container,
        job_runner=job_runner,
        server_mode=server_mode,
        config_path=resolved_config_path,
    )


def build_session(process: ProcessContext) -> DependencyContainer:
    """Build one user's stateful services into a fresh child of the process container.

    Cheap and safe to call once per request or tenant: nothing it constructs is shared
    with another session, and the process container is only read (its singletons are
    resolved lazily through the child's fallback). Services are constructed in the
    same dependency order ``bootstrap()`` always used.

    Args:
        process: The :class:`ProcessContext` from :func:`bootstrap_process`.

    Returns:
        The session container. ``resolve(ApplicationState)``, ``resolve(SettingsService)``
        and the other per-user services are this session's own; ``AppConfig``,
        ``JobRunner``, ``PersistenceService`` (and ``PluginManager`` outside server mode)
        come from ``process``.
    """
    logger = get_logger(__name__)
    config = process.config
    session = DependencyContainer(parent=process.container)

    # Application state: depends on nothing else here, but is registered into the
    # container like everything else so consumers resolve it the same way.
    state = ApplicationState()
    session.register(ApplicationState, lambda: state, singleton=True)
    logger.debug("Registered ApplicationState into the session container.")

    # Step 5: milestone 1b-i's services. Constructed after
    # ApplicationState for consistency with the "core services first"
    # ordering above, though none of these three currently depend on
    # ApplicationState directly. ProjectService is seeded with
    # config.recent_projects so a freshly booted session remembers
    # projects opened in a previous run, rather than starting with an
    # empty recent-projects list every time despite config.yaml
    # already tracking one. (In server mode the config's recent_projects is
    # always empty -- see _server_mode_config -- and process.config_path is
    # None, so SettingsService is in-memory: it never touches config.yaml.)
    settings_service = SettingsService(config, process.config_path)
    session.register(SettingsService, lambda: settings_service, singleton=True)
    logger.debug("Registered SettingsService into the session container.")

    project_service = ProjectService(recent_projects=config.recent_projects)
    session.register(ProjectService, lambda: project_service, singleton=True)
    logger.debug("Registered ProjectService into the session container.")

    workspace_service = WorkspaceService()
    session.register(WorkspaceService, lambda: workspace_service, singleton=True)
    logger.debug("Registered WorkspaceService into the session container.")

    # Milestone 9: depends on the WorkspaceService instance just
    # registered above (resolves/mutates datasets and visualizations
    # through it, exactly as AssistantService does) — registered after
    # it for the same "construct in dependency order" reasoning this
    # function already documents for every service above.
    analysis_orchestrator_service = AnalysisOrchestratorService(workspace_service)
    session.register(
        AnalysisOrchestratorService,
        lambda: analysis_orchestrator_service,
        singleton=True,
    )
    logger.debug("Registered AnalysisOrchestratorService into the session container.")

    # Milestone 26: depends on the AnalysisOrchestratorService instance just
    # registered above (reads its propose_next_stage() as one of
    # GuidanceService's own four deterministic suggestion sources), for the
    # same "construct in dependency order" reasoning already documented
    # above -- registered here, immediately after it, per the plan's own
    # "Registered in bootstrap() after AnalysisOrchestratorService" note.
    guidance_service = GuidanceService(analysis_orchestrator_service)
    session.register(GuidanceService, lambda: guidance_service, singleton=True)
    logger.debug("Registered GuidanceService into the session container.")

    # Milestone 13: depends on both WorkspaceService and
    # AnalysisOrchestratorService instances just registered above, for
    # the same "construct in dependency order" reasoning documented
    # above — ReportService replays AnalysisOrchestratorService's log
    # and resolves visualizations through WorkspaceService, and needs
    # both to already exist.
    report_service = ReportService(workspace_service, analysis_orchestrator_service)
    session.register(ReportService, lambda: report_service, singleton=True)
    logger.debug("Registered ReportService into the session container.")

    # Milestone 14: depends on SettingsService for saved (credential-
    # free) connection profiles — see DatabaseConnectionService's own
    # docstring for why live connections/passwords are kept purely
    # in-memory and never routed through SettingsService at all.
    database_connection_service = DatabaseConnectionService(settings_service)
    session.register(
        DatabaseConnectionService, lambda: database_connection_service, singleton=True
    )
    logger.debug("Registered DatabaseConnectionService into the session container.")

    return session


def bootstrap(
    config_path: Path | None = None, log_dir: Path | None = None
) -> BootstrapContext:
    """Run application startup and return a ready-to-use context (the legacy desktop entry point).

    One process, one session: this composes :func:`bootstrap_process` and
    :func:`build_session` and returns exactly the :class:`BootstrapContext` it always
    did. It is also the only caller of ``set_default_job_runner`` (see below).

    Args:
        config_path: Location of the YAML configuration file. Defaults
            to ``<data root>/config/config.yaml`` -- the project's standard config
            location unless ``UADAS_DATA_ROOT`` relocates it; overridable
            primarily for tests that want an isolated config file.
        log_dir: Directory rotating log files are written into.
            Defaults to ``<data root>/logs``; same
            override rationale as ``config_path``.

    Returns:
        A populated :class:`BootstrapContext`.

    Raises:
        ConfigError: If configuration cannot be loaded or is invalid.
            Propagates from :meth:`AppConfig.load` unchanged, since it
            is already a specific, actionable
            :class:`~uadas_core.core.exceptions.ApplicationError` subclass.
        BootstrapError: If a startup step completes but produces a
            result a later step cannot use. Config and logging
            failures raise their own more specific exception types
            instead (see above); this is reserved for genuine
            sequencing failures in this function itself.
    """
    process = bootstrap_process(
        server_mode=False, config_path=config_path, log_dir=log_dir
    )

    # Two registration paths for the runner, on purpose:
    #  * the container registration (done in bootstrap_process) is the real DI
    #    wiring every new consumer should use (resolve JobRunner from the container).
    #  * set_default_job_runner() is a Phase-1.2-only bridge so
    #    src.workers.base_worker.BaseWorker.run() can reach the SAME instance
    #    without a change to BaseWorker's public __init__ signature (de-risking
    #    plan Control A10). Both must hand out the identical object -- asserted
    #    by tests/core/test_bootstrap.py. The bridge dies with BaseWorker in
    #    Phase 2; see uadas_core.jobs.__init__'s docstring. It is a process
    #    global, so it lives here in the single-user legacy entry point and NOT
    #    in bootstrap_process: server-mode code never goes through it.
    set_default_job_runner(process.job_runner)

    session = build_session(process)
    state = session.resolve(ApplicationState)
    context = BootstrapContext(config=process.config, container=session, state=state)

    if context.config is None or context.container is None or context.state is None:
        # Defensive check: should be unreachable given the assignments
        # above, but guards against a future edit to this function
        # accidentally constructing BootstrapContext from a step that
        # silently returned an unusable value.
        raise BootstrapError(
            "Bootstrap sequence completed but produced an incomplete "
            "context. This indicates a bug in bootstrap() itself."
        )

    get_logger(__name__).info("Bootstrap sequence complete.")
    return context
