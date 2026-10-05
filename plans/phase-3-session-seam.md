# Phase 3 — core session seam (between 3.3 and 3.4)

**Status:** implemented on `phase-3/django-backend`. Rulings 2 and 3 of
[phase-3-readiness.md](phase-3-readiness.md) are the brief; this records the design and its limits.

## Design

`bootstrap()` built one desktop user's world. It is now two halves in `uadas_core/bootstrap.py`:

- `bootstrap_process(*, server_mode=False, config=None) -> ProcessContext` — built **once** per process.
- `build_session(process) -> DependencyContainer` — built **per user/request**: a *child* of the process
  container (`DependencyContainer(parent=...)`: own registrations first, parent fallback, no leakage to
  parent or siblings, singleton construction guarded by a lock).
- `bootstrap()` stays: one process + one session, same `BootstrapContext`, still the only caller of
  `set_default_job_runner`. Pinned by `tests/core/test_bootstrap_characterization.py` (written green
  against the old code first).

## Per-process vs per-session, and why

| Process (shared, tenant-free) | Why safe |
|---|---|
| `AppConfig`, built-in operation/chart/renderer registries | immutable / populated once, read-only after |
| `JobRunner` (`ProcessContext.job_runner`) | stateless between jobs; one pool, not one per tenant |
| `PersistenceService` | stateless; storage base is a per-call argument |
| `PluginManager` (desktop only) | mutates global registries + `sys.path`: never in server mode |

| Session (private) | Why |
|---|---|
| `ApplicationState`, `WorkspaceService` | datasets/visualizations/dashboards of one user |
| `SettingsService` | mutable settings; in-memory in server mode (never writes `config.yaml`) |
| `ProjectService`, `DatabaseConnectionService` | recent projects, live connections and passwords |
| `AnalysisOrchestratorService`, `GuidanceService`, `ReportService` | analysis logs and anything derived from the workspace |

One ordering change vs HEAD: plugins now load before the session services are built (pinned in
`test_bootstrap_characterization.py`; safe because no service constructor reads a registry).

## Server-mode guarantees (`server_mode=True`, the server half of 3.8)

- **No plugins:** `uadas_core.plugins` is not imported (fresh-interpreter probe), no `PluginManager`,
  `sys.path` and the plugin registries untouched; the config is normalised to `plugins.enabled=False`.
- **No YAML:** config only from the passed `AppConfig` / `AppConfig.defaults()`; `config_path`/`log_dir`
  arguments are rejected (`BootstrapError`); desktop `recent_projects` and saved DB profiles are cleared so
  they are not seeded into every tenant. Spy test: no `yaml` call and no write-mode `open()`.
- **No log files, host logging untouched:** stderr only, via a handler on the `uadas_core` logger with
  `propagate=False` (`configure_logging(server_mode=True)`); the root logger (Django's) is never changed and no
  directory is created. Logging is mode-aware: configuring the other mode afterwards raises.
- **No tenant data or secrets in logs:** `ApplicationState` logs names/ids, `SettingsService.set` logs the key
  path, never `%r` of an object or value. The API refuses `UADAS_CORE_LOG_LEVEL=DEBUG` unless Django `DEBUG`
  is on (bridge, at runtime) and in prod settings (at start-up). Not covered: `analysis/t_test.py` and
  `cleaning/missing_values.py` still log group labels / a fill value at INFO.
- **Process mode latch** (`core/process_mode.py`): the first `bootstrap_process` claims desktop or server, a
  conflicting later call (`bootstrap()`, `bootstrap_process(server_mode=False)`, or desktop-then-server)
  raises `BootstrapError` before any I/O. The `.importlinter` ignore edges (below) still let `uadas_api`
  *import* the legacy functions; the latch is the runtime backstop, tests reset it via a documented function.
- **Secrets:** providers store only an env-var *name*; keys come from the environment
  (`ProviderRotationService` `secrets` mapping), DB passwords live only in connection objects. Audit of
  every disk write in `uadas_core`: `config.py` default write and `SettingsService.save` (both unreachable in
  server mode), logger file (off), `PersistenceService` (caller-supplied base, 3.4), `ProjectService.
  save_project` and report exporters (caller-supplied path). None writes a secret.
- **No `PROJECT_ROOT` dependence:** `UADAS_DATA_ROOT` (`constants.data_root()` & friends) overrides the
  anchor for fixed data paths; must be absolute (relative -> `ConfigError`), normalised; unset = today's
  behaviour. Server mode touches none of them.
- **No global runner bridge:** sessions get the runner through the container; the bridge is installed only by
  legacy `bootstrap()`.

`apps/api/uadas_api/core_bridge.py`: `get_process_context()` (lazy, cached, locked),
`new_session()`, config built from Django settings (`UADAS_CORE_LOG_LEVEL`). No endpoint, no storage.

## Import-linter

`ai.assistant_service -> services.workspace_service` and `core.application_state -> models` exemptions are
gone (Protocols `AssistantWorkspace`, `ProjectLike`/`DatasetLike`/`VisualizationLike`; conformance is checked
by mypy in `services/_protocol_conformance.py`). One new exemption:
four `uadas_core.bootstrap -> {jobs, plugins}` edges in the `api-avoids-plugins-and-jobs` contract, because the
API must call the composition root; direct imports are still forbidden, and "server mode never imports the
plugin package" is a runtime test, not a static one.

## NOT solved

- `PersistenceService` still writes a local filesystem; object storage and tenant-keyed frames are 3.4.
- A session is empty: loading a tenant's datasets (per-request Parquet cost, lazy frames) is unsolved.
- Module-global registries (`reader_registry._PLUGIN_READERS`, built-ins) are shared by design; a future
  per-tenant plugin story would need scoped registries.
- `logger._configured` is still a once-per-process global (now lock-guarded); `ThreadPoolExecutorJobRunner`
  is in-process — durable jobs are 3.5.
- No per-session eviction/TTL: the caller owns a session's lifetime.
