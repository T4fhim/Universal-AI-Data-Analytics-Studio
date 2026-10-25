# Phase 3.5 — Jobs and the parser sandbox (with the sandbox half of 3.8)

**Branch:** `phase-3/django-backend` · **Code:** `apps/api/uadas_api/{jobs,sandbox,ingest}/`, `settings/_jobs.py` ·
**Prior:** [phase-3-4-storage.md](phase-3-4-storage.md), [phase-3-readiness.md](phase-3-readiness.md) (rulings 3, assumption 2)
**Scope:** durable background jobs with a real worker, the `Job` row, the sandboxed parser, the `ingest_dataset` job.
**Not here:** the upload endpoint (3.6), SSE (3.7), quotas, the rest of 3.8 (SQL capability, Schemathesis).
**Revised after two independent reviews** (a security review of the sandbox, a Django/Celery review of the job layer); the
sections below state what each layer *really* guarantees, including what an earlier draft over-claimed.

## Queue decision: Celery + Redis behind a facade

`django.tasks` (6.1) ships only `ImmediateBackend` and `DummyBackend` (dev/test). The third-party backends implement enqueue and result
lookup but none gives **late acknowledgement with redelivery, a visibility timeout, hard/soft time limits, bounded retries with
backoff**. Celery 5.6 has all of them as configuration. So the courier is Celery; the contract is `django.tasks`-shaped
(`enqueue(id)`), and **only `jobs/{celery_app,tasks,queue}.py` import it** (`test_jobs_boundary.py`). The message is **a job id string,
JSON** — never pickle (`accept_content=["json"]`, proved on the live app) — and every worker action re-derives organization, project and
creator from the database row and re-checks the creator's role. Delivery is at-least-once; idempotence comes from the database.
Redis: the queue is moved to **a different database number than the cache** (`REDIS_URL` alone is rewritten to `/1`, or `/2` if the cache is
on 1; production refuses a collision) because Django's `cache.clear()` flushes the whole database and would delete queued messages.

## `Job` and its state machine

`queued → running → succeeded | failed | cancelled`, plus `running → queued` (retry). Terminal is immutable on **every** write path:
`save()` (the remembered status **and**, at write time, the stored status under `SELECT … FOR UPDATE` in the same transaction, so a stale
instance cannot resurrect a finished job), `queryset.update()` (terminal rows excluded; status only inside `allow_status_write()`), and DB check constraints.

* **Fencing.** `attempts` is incremented by every claim and is the worker's token: *every* worker-side write (`finish_succeeded/failed/cancelled`,
  `requeue_for_retry`, `ProgressSink.report`, `check_cancelled`, the heartbeat) filters `attempts = <my attempt>`. A worker whose heartbeat went
  stale and was taken over can no longer fail, requeue, cancel, report for or commit the run that replaced it, and does not abandon the dataset
  (`test_jobs_hardening.py`: two interleaved workers, each refusal with its accepted twin).
* **Heartbeat for the whole run.** A thread (`progress.Heartbeat`, interval = ¼ of `JOBS_STALE_AFTER_SECONDS`, 1-60 s) beats while the handler is
  busy and silent (100 MB download, up to `SANDBOX_WALL_SECONDS` of parsing, 512 MB upload). A failed beat flags the loss and the next checkpoint raises.
  Settings refuse a configuration in which `JOBS_STALE_AFTER_SECONDS` or `JOBS_TIME_LIMIT_SECONDS` is not more than `SANDBOX_WALL_SECONDS + 60`.
  `JOBS_STALE_AFTER_SECONDS` now defaults to 300.
* **The sweeper cleans up like a worker.** A stale `running` job it fails (`worker_lost`) or cancels, and a *queued* job cancelled by a user, run the
  kind's abandon hook, so the original upload and any staged frame reach the 3.4 outbox (an OOM-killed worker is the common way objects get orphaned).
  A requeue abandons nothing. It also reaps stale sandbox directories (below).
* **A retry waits.** `requeue_for_retry` stores `not_before` (now + backoff) and `enqueued_at = now` (the retry's message is in flight); the
  lost-message sweeper honours `not_before`, so it cannot re-send a backing-off job every 60 s.
* **Ingest commit.** The `DatasetRecord` and the `succeeded` transition commit in one transaction; failure injection now reaches *the commit itself*
  (the success update finding nothing to update after the record was created; a database error inside the transaction) and asserts no record, the
  frame deleted or queued, the dataset condemned or not as appropriate.

## Parser sandbox: threat model, and what each layer really does

Threat: a hostile PDF/Office/XML/zip/image drives camelot, PyMuPDF, pdfplumber, python-docx, openpyxl, lxml, OpenCV or Tesseract into code
execution, memory/CPU exhaustion, file read, network access or a fork bomb — in a process that holds other tenants' data.

| Layer | What it really does | What it does **not** do |
|---|---|---|
| Admission (`admission.py`) | extension table (derived from the readers, parity-tested both ways) + content signature + zip central-directory budget + size cap | The zip budget reads **declared** sizes, which are attacker-controlled (`test_a_zip_that_lies…` forges one and passes). The real bound is the child's rlimits. `.gz/.gzip` are **not admitted** (the reader could never pick a reader for `input.gz`; refused up front, listed in `NOT_ADMITTED_EXTENSIONS`). |
| Child process (`python -I -m …child`) | separate interpreter, explicit environment, own cwd/TMP/HOME, JSON in/out, reply capped, no Django | The stripped environment protects *the child's own* env. It protects nothing of the worker's by itself (below). |
| rlimits (Linux) | `RLIMIT_AS/CPU/FSIZE/NOFILE/NPROC/CORE`, each read back and reported; the parent refuses a reply missing `memory, cpu, fsize` (+ `nproc` when it applies) | `RLIMIT_NPROC` is per-uid and not enforced for root. |
| Hardening (child) | `PR_SET_DUMPABLE=0`, `NO_NEW_PRIVS`, `PR_SET_PDEATHSIG=SIGKILL` (+ the parent-pid race check), own `alarm` above the wall limit | A grandchild that calls `setsid()` leaves the process group and **survives** `killpg` (and PDEATHSIG is not inherited): the bound is `RLIMIT_NPROC` and the deployment's cgroup `pids_limit`, not this code. |
| Worker hardening (`isolation.harden_worker`) | the worker is non-dumpable, so a same-uid child cannot read `/proc/<worker>/{environ,mem,…}` (**reproduced and fixed**: before, a child read the worker's `SECRET_KEY` / `DATABASE_URL`) | Files: a same-uid child can still read everything the worker's uid can, including **other jobs' input** (`test_same_uid_children_can_read_each_others_files…` says so). `0700` separates users, not processes of one user. |
| Dedicated child uid (`SANDBOX_CHILD_UID/GID`) | the child runs as another user (worker needs root or `CAP_SETUID/SETGID/CHOWN`); the job dir is chowned to it; root workers regain `RLIMIT_NPROC` for the child | Concurrent children share that one uid, so they can still read each other's directories; per-job uids or a container per job separate those. |
| Network namespace (`guards.isolate_network`) | `unshare(CLONE_NEWNET)` (with `CLONE_NEWUSER` unprivileged), loopback-only **verified**, capabilities dropped; reported as `network_isolated` | Needs unprivileged user namespaces: Docker's default seccomp profile and Ubuntu 24.04's AppArmor restriction refuse it (the child then reports `False`). A side effect, **not relied on**: inside a new user namespace the child cannot read its parent's `/proc` even as the same uid. |
| Socket shim (`install_network_block`) | catches honest mistakes and noisy attacks; remembers swallowed attempts | **Bypassable** — `socket.socket.__mro__` reaches the raw `_socket` class (`test_…raw_socket_bypass…` shows a raw connect succeeding when no namespace exists). It is reported as `network_guard` and is **not counted as enforcement**. |
| Verification (`runner.py`) | strict JSON schema, closed error codes, output opened `O_NOFOLLOW`, size/magic/SHA-256 checked, nothing parsed in the parent | Row/column counts are the child's claim (capped). |
| Static + runtime boundary | `.importlinter` contract (direct imports only) + fresh-interpreter tests: the **parent side** and the **composition root** (`core_bridge` building the server-mode process context) load no `uadas_core.readers.*` module and no parse-only library (fitz, camelot, pdfplumber, cv2, pytesseract, pptx, odf, pyxlsb, bs4). openpyxl, python-docx and lxml *are* loaded there, but only because the core's report *exporters* write `.xlsx/.docx` with them (asserted: they appear only with an exporter module loaded). | The contract cannot see indirect imports; the runtime test is what covers `core_bridge`. |
| XML (`uadas_core/readers/xml_reader.py`) | the parser is pinned: `resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False` (no XXE, no entity bomb, independent of the installed lxml's defaults) | — |

**Cleanup after a dead worker.** A worker killed with SIGKILL (Celery's hard time limit, the OOM killer) cannot delete its job directory, which holds a
tenant's file. The child dies with it (PDEATHSIG); the directory is removed by `reap_stale_workspaces` (prefix `uadas-sbx-`, a real directory, owned by us
or the child uid, untouched for longer than the Celery hard limit + 5 min and never under 30 min), run when a worker/process starts, when a process
opens its first workspace, and on every sweeper run. Settings require the Celery hard limit to exceed the sandbox wall clock by more than 60 s.

### What production demands (settings fail closed; `check --deploy` re-checks)

| Setting | Meaning |
|---|---|
| `SANDBOX_CHILD_UID` + `SANDBOX_CHILD_GID` **or** `SANDBOX_ISOLATION_ACKNOWLEDGED=container` | something separates the child from the worker; a root worker with neither is `uadas_jobs.E005`; a uid the worker cannot switch to is `E006` |
| `SANDBOX_NETWORK_ISOLATION` = `unshare` \| `container` \| `none-acknowledged` | `unshare` refuses a parse whose child could not isolate (and `E007` if the host cannot); `container` = the worker has no route out (stated, not measured); `none-acknowledged` = accept the bypassable shim alone, explicitly |
| Linux, unprivileged or dedicated uid, packages in the interpreter's site-packages (not `pip install --user`: `E004`) | rlimits are only meaningful on Linux |
| `CELERY_BROKER_URL` on a database other than the cache's | `different Redis databases` error otherwise |
| Native libraries `libgl1 libglib2.0-0 libxcb1` | the readers import OpenCV; without them every parse fails as `parse_error` (verified in a bare `python:3.13-slim`) |

Real network isolation is still **a container with no network** (or the namespace above where the kernel allows it); a compose sketch is in `docker-compose.dev.yml`.

## Verification, and what only Linux CI can prove

Hermetic everywhere: fencing, heartbeat, sweeper cleanup, settings, checks, admission, the enforcement gate (fake children with exact replies), XML hardening.
Proved here in a Linux container (`python:3.13`, uid 10001): rlimits, the `/proc` hardening (with the positive twin that the unhardened probe *does* read the
parent's environment), PDEATHSIG + dir reaping after `kill -9`, the child's own alarm, `network_isolated` + the `_socket` bypass (with `--security-opt
seccomp=unconfined`; under Docker's default profile the honest `False` is asserted instead), the dedicated-uid tests (root container). **Only a real CI runner
can prove**: that the runner's kernel allows (or honestly refuses) the namespace (`SANDBOX_REQUIRE_NETNS` is set only if `unshare --user --net` works there);
the skip count on that image (8, with no spare: see `ci.yml`); a real `celery worker` against the service containers; behaviour under a real cgroup `pids_limit`.

## Not solved (said plainly)

No seccomp/namespaces *around the parse* beyond the network namespace: a compromised child can still `exec` any binary it can reach and write anywhere its uid
may; the Parquet it writes is later parsed by pyarrow in a privileged process (a crafted file is a residual risk); concurrent children of one uid read each
other's directories; `setsid()` grandchildren survive a kill (bounded by `RLIMIT_NPROC` / `pids_limit`); a kernel/hypervisor escape is out of scope; no quotas; Windows
is dev-only (no limits, `prod` refuses to start); a worker killed mid-job is redelivered only after the visibility timeout (the sweeper covers the rest); the sweeper
has no leader election (it is idempotent instead).
