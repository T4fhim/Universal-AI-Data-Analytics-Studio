# File: apps/api/tests/test_migrations.py
"""The committed migrations match the models and form the graph we intend.

Why: a model change without its migration only fails at deploy time, and a migration
graph with a wrong cross-app dependency can apply in the wrong order on a fresh database.
So the suite checks (a) ``makemigrations --check`` finds nothing left to generate,
(b) every app that has models has exactly the migrations listed in ``EXPECTED_MIGRATIONS``
(so none appears by accident) and ``ai`` (no models yet) has none, (c) the cross-app dependencies are the ones the foreign keys require, and
(d) the user model really is ``accounts.User`` in the migration state -- the thing that
cannot be changed after the first migration is applied anywhere.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader

# Every migration each model app is expected to have, in order. This was "exactly one
# 0001_initial per app" through 3.4; 3.5 adds `jobs` (its initial) and the first follow-up
# migration anywhere (workspaces 0002: DatasetRecord.sha256). Adding a migration is a
# deliberate edit here -- the point of the pin is that none appears by accident.
EXPECTED_MIGRATIONS: dict[str, list[str]] = {
    "accounts": ["0001_initial"],
    "workspaces": ["0001_initial", "0002_datasetrecord_sha256_and_more"],
    "pipeline": ["0001_initial"],
    "exports": ["0001_initial"],
    "jobs": ["0001_initial", "0002_job_not_before"],
}
MODEL_APPS = tuple(EXPECTED_MIGRATIONS)


def _loader() -> MigrationLoader:
    return MigrationLoader(None, ignore_no_migrations=True)


@pytest.mark.django_db
def test_makemigrations_check_finds_nothing_to_generate() -> None:
    # --check exits non-zero (SystemExit) when a model change has no migration.
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)


@pytest.mark.parametrize("app", MODEL_APPS)
def test_each_model_app_has_exactly_its_expected_migrations(app: str) -> None:
    names = sorted(name for (label, name) in _loader().disk_migrations if label == app)
    assert names == EXPECTED_MIGRATIONS[app]


def test_the_ai_app_has_no_models_and_no_migrations() -> None:
    assert list(apps.get_app_config("ai").get_models()) == []
    assert not [k for k in _loader().disk_migrations if k[0] == "ai"]


def test_there_are_no_migration_conflicts() -> None:
    assert _loader().detect_conflicts() == {}


def _dependencies(app: str) -> set[tuple[str, str]]:
    migration = _loader().disk_migrations[(app, "0001_initial")]
    return {(label, name) for label, name in migration.dependencies}


def test_cross_app_dependencies_follow_the_foreign_keys() -> None:
    assert ("accounts", "0001_initial") in _dependencies("workspaces")
    assert {
        ("accounts", "0001_initial"),
        ("workspaces", "0001_initial"),
    } <= _dependencies("pipeline")
    assert {
        ("accounts", "0001_initial"),
        ("workspaces", "0001_initial"),
    } <= _dependencies("exports")
    assert {
        ("accounts", "0001_initial"),
        ("workspaces", "0001_initial"),
    } <= _dependencies("jobs")


def test_the_workspaces_migration_depends_on_the_swappable_user_model() -> None:
    # Project.created_by points at AUTH_USER_MODEL; a hard-coded "accounts.User" would
    # break the swappable-model contract.
    migration = _loader().disk_migrations[("workspaces", "0001_initial")]
    assert any(
        getattr(dep, "setting", None) == settings.AUTH_USER_MODEL  # "accounts.User"
        for dep in migration.dependencies
    )


def test_the_migrations_apply_in_dependency_order_to_one_leaf_per_app() -> None:
    loader = _loader()
    leaves = {key for key in loader.graph.leaf_nodes() if key[0] in MODEL_APPS}
    assert leaves == {(app, EXPECTED_MIGRATIONS[app][-1]) for app in MODEL_APPS}


def test_auth_user_model_is_set_to_the_accounts_user() -> None:
    assert settings.AUTH_USER_MODEL == "accounts.User"
    state = _loader().project_state()
    assert ("accounts", "user") in state.models
    # Django's own auth.User survives in migration state only as a swapped-out stub.
    assert state.apps.get_model("auth", "user")._meta.swapped == "accounts.User"
