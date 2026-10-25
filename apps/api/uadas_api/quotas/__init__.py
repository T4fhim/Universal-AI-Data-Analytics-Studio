# File: apps/api/uadas_api/quotas/__init__.py
"""Per-tenant quotas (Phase 3.8): how much one organization may consume, enforced atomically.

Why a package that imports nothing: it is a Django app (it owns three tables), and Django loads
app modules before the model registry is ready. Use the submodules:

* :mod:`uadas_api.quotas.choices` -- :class:`UsageKind`, the closed set of metered resources and
  which window each uses (a standing total, or a calendar month).
* :mod:`uadas_api.quotas.models` -- :class:`OrganizationQuota` (an organization's limit overrides),
  :class:`UsageCounter` (what has been used in a window: the row the atomic update targets) and
  :class:`UsageLedger` (one row per charge, unique per ``source_key`` so a retry cannot be billed
  twice).
* :mod:`uadas_api.quotas.service` -- :func:`reserve` (strict: one conditional ``UPDATE``),
  :func:`charge` (after the fact, never refused), :func:`release`, :func:`assert_available`.
* :mod:`uadas_api.quotas.errors` -- :class:`QuotaExceededError`, which the API answers ``429
  quota_exceeded``.

The deployment-wide default limits come from ``settings.UADAS_QUOTA`` (``settings/_quota.py``).
"""
