# File: apps/api/tests/test_storage_keys.py
"""Object keys (3.4): fixed layouts built in one place, and a validator that fails closed.

Why: a key is the only thing separating one tenant's object from another's in a shared
bucket, and the one place user input could leak into it is a file name. These tests pin that
(a) every key has a fixed layout under ``<organization_id>/``; (b) a caller-supplied name can
never become a key segment -- the builders take identifiers, not names; (c) the validator
refuses traversal, look-alike Unicode, NUL, over-long and other-tenant keys. Each reject
case has an accept twin, so the validator cannot pass by rejecting everything.
"""

from __future__ import annotations

import re
import uuid

import pytest

from uadas_api.storage import keys
from uadas_api.storage.errors import InvalidKeyError

ORG = uuid.UUID("11111111-2222-4333-8444-555555555555")
OTHER_ORG = uuid.UUID("99999999-8888-4777-8666-555555555555")
DATASET = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
PROJECT = uuid.UUID("12345678-1234-4234-8234-123456789abc")
REPORT = uuid.UUID("fedcba98-7654-4321-8abc-0123456789ab")


# --- layouts ----------------------------------------------------------------------


def test_the_original_key_has_the_fixed_layout_and_is_unique_per_call() -> None:
    first = keys.dataset_original_key(ORG, DATASET)
    second = keys.dataset_original_key(ORG, DATASET)
    assert re.fullmatch(f"{ORG}/datasets/{DATASET}/original/[0-9a-f]{{32}}", first)
    assert first != second


def test_the_frame_key_embeds_the_save_token() -> None:
    token = keys.new_save_token(7)
    assert re.fullmatch(r"g0000007-[0-9a-f]{12}", token)
    assert (
        keys.dataset_frame_key(ORG, DATASET, token)
        == f"{ORG}/datasets/{DATASET}/frames/{token}.parquet"
    )


def test_two_save_attempts_at_one_version_never_share_a_token() -> None:
    assert keys.new_save_token(3) != keys.new_save_token(3)


def test_the_workspace_database_key_has_the_fixed_layout() -> None:
    token = keys.new_save_token(1)
    assert (
        keys.workspace_db_key(ORG, PROJECT, token)
        == f"{ORG}/projects/{PROJECT}/workspace/{token}/workspace.db"
    )


def test_the_export_key_has_the_fixed_layout() -> None:
    key = keys.export_key(ORG, REPORT, "pdf")
    assert re.fullmatch(f"{ORG}/exports/{REPORT}/[0-9a-f]{{32}}\\.pdf", key)


def test_prefix_helpers_are_the_directories_the_layouts_live_in() -> None:
    assert keys.dataset_prefix(ORG, DATASET) == f"{ORG}/datasets/{DATASET}/"
    assert keys.project_prefix(ORG, PROJECT) == f"{ORG}/projects/{PROJECT}/"
    assert keys.organization_prefix(ORG) == f"{ORG}/"


def test_identifiers_are_normalised_to_canonical_lowercase_uuids() -> None:
    upper = str(DATASET).upper()
    assert keys.dataset_prefix(str(ORG).upper(), upper) == f"{ORG}/datasets/{DATASET}/"
    assert keys.dataset_prefix(ORG, str(DATASET)) == keys.dataset_prefix(ORG, DATASET)


# --- builders take identifiers, never names ---------------------------------------


@pytest.mark.parametrize(
    "not_an_id",
    [
        "../x",
        "a/b",
        "",
        "report.pdf",
        "..",
        "%2e%2e",
        "x" * 40,
        "\x00",
        "../../etc/passwd",
    ],
)
def test_a_builder_refuses_an_identifier_that_is_not_a_uuid(not_an_id: str) -> None:
    with pytest.raises(InvalidKeyError):
        keys.dataset_original_key(ORG, not_an_id)
    with pytest.raises(InvalidKeyError):
        keys.export_key(ORG, not_an_id, "pdf")
    with pytest.raises(InvalidKeyError):
        keys.dataset_original_key(not_an_id, DATASET)


def test_a_builder_accepts_a_uuid_in_every_spelling_it_documents() -> None:
    for spelling in (DATASET, str(DATASET), str(DATASET).upper()):
        assert keys.dataset_original_key(ORG, spelling).startswith(f"{ORG}/datasets/")


@pytest.mark.parametrize("token", ["", "a/b", "..", "g1 2", "g1\n", "x" * 65, "é"])
def test_a_save_token_must_be_a_plain_short_segment(token: str) -> None:
    with pytest.raises(InvalidKeyError):
        keys.dataset_frame_key(ORG, DATASET, token)
    with pytest.raises(InvalidKeyError):
        keys.workspace_db_key(ORG, PROJECT, token)


@pytest.mark.parametrize("token", ["g0000001-abcdef123456", "a", "A-b-9", "x" * 64])
def test_a_plain_short_save_token_is_accepted(token: str) -> None:
    assert keys.dataset_frame_key(ORG, DATASET, token).endswith(f"/{token}.parquet")


@pytest.mark.parametrize(
    "extension", ["", ".pdf", "PDF", "p/df", "pdf.exe", "toolongext1", "p df", "é"]
)
def test_an_export_extension_must_be_a_short_lowercase_alphanumeric(
    extension: str,
) -> None:
    with pytest.raises(InvalidKeyError):
        keys.export_key(ORG, REPORT, extension)


@pytest.mark.parametrize("extension", ["pdf", "docx", "csv", "json", "md", "x7"])
def test_a_short_lowercase_alphanumeric_extension_is_accepted(extension: str) -> None:
    assert keys.export_key(ORG, REPORT, extension).endswith(f".{extension}")


def test_no_builder_accepts_a_file_name() -> None:
    """The user's file name is metadata, never a key segment (the signatures prove it)."""
    import inspect

    for builder in (
        keys.dataset_original_key,
        keys.dataset_frame_key,
        keys.workspace_db_key,
        keys.export_key,
    ):
        names = set(inspect.signature(builder).parameters)
        assert not names & {"filename", "name", "file_name", "path", "original_name"}


# --- the validator -----------------------------------------------------------------

GOOD = [
    f"{ORG}/datasets/{DATASET}/original/{'a' * 32}",
    f"{ORG}/exports/{REPORT}/{'b' * 32}.pdf",
    f"{ORG}/a.b-c_d/e",
    f"{ORG}/x",
    f"{ORG}/" + "/".join(["seg"] * 20),
]

BAD = [
    pytest.param(f"{OTHER_ORG}/datasets/x", id="other-tenant"),
    pytest.param("datasets/x", id="no-prefix"),
    pytest.param(f"{ORG}", id="bare-org"),
    pytest.param(f"{ORG}/", id="bare-prefix"),
    pytest.param(f"/{ORG}/x", id="leading-slash"),
    pytest.param(f"{ORG}/../{OTHER_ORG}/x", id="dotdot-into-other-tenant"),
    pytest.param(f"{ORG}/a/../b", id="dotdot-middle"),
    pytest.param(f"{ORG}/./x", id="dot-segment"),
    pytest.param(f"{ORG}/a//b", id="empty-segment"),
    pytest.param(f"{ORG}/a/", id="trailing-slash"),
    pytest.param(f"{ORG}/a./b", id="trailing-dot"),
    pytest.param(f"{ORG}/%2e%2e/x", id="percent-encoded-dotdot"),
    pytest.param(f"{ORG}/a b", id="space"),
    pytest.param(f"{ORG}/a\\b", id="backslash"),
    pytest.param(f"{ORG}/a\x00b", id="nul"),
    pytest.param(f"{ORG}/a\nb", id="newline"),
    pytest.param(f"{ORG}/a\tb", id="tab"),
    pytest.param(f"{ORG}/．．/x", id="fullwidth-dots"),
    pytest.param(f"{ORG}/a․b", id="one-dot-leader"),
    pytest.param(f"{ORG}/ａbc", id="fullwidth-a"),
    pytest.param(f"{ORG}/аbc", id="cyrillic-a"),
    pytest.param(f"{ORG}/café", id="accented"),
    pytest.param(f"{ORG}/a‮b", id="bidi-override"),
    pytest.param(f"{ORG}/" + "x" * 129, id="segment-too-long"),
    pytest.param(f"{ORG}/" + "/".join(["abcdefghij"] * 60), id="key-too-long"),
]


@pytest.mark.parametrize("key", GOOD)
def test_a_plain_key_under_the_organization_is_accepted(key: str) -> None:
    assert keys.check_key(ORG, key) == key


@pytest.mark.parametrize("key", BAD)
def test_every_other_key_is_refused(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        keys.check_key(ORG, key)


def test_the_organization_prefix_must_be_the_canonical_lowercase_spelling() -> None:
    # An organization whose id has letters, so upper-casing actually changes it.
    org = uuid.UUID("abcdef01-2345-4678-8abc-def012345678")
    assert keys.check_key(org, f"{org}/x") == f"{org}/x"
    with pytest.raises(InvalidKeyError):
        keys.check_key(org, f"{str(org).upper()}/x")


def test_a_key_of_exactly_the_maximum_length_is_accepted_and_one_more_is_not() -> None:
    prefix = f"{ORG}/"
    fill = keys.MAX_KEY_LENGTH - len(prefix)
    # Segments of at most 128 characters, joined with single slashes, up to the limit.
    parts: list[str] = []
    remaining = fill
    while remaining > 0:
        size = min(100, remaining)
        parts.append("a" * size)
        remaining -= size + 1  # the separating slash
    exact = prefix + "/".join(parts)
    exact = exact[: keys.MAX_KEY_LENGTH].rstrip("/")
    assert len(exact) <= keys.MAX_KEY_LENGTH
    assert keys.check_key(ORG, exact) == exact
    with pytest.raises(InvalidKeyError):
        keys.check_key(ORG, exact + "/" + "a" * (keys.MAX_KEY_LENGTH - len(exact)))


def test_a_non_string_key_is_refused_not_coerced() -> None:
    with pytest.raises(InvalidKeyError):
        keys.check_key(ORG, None)  # type: ignore[arg-type]
    with pytest.raises(InvalidKeyError):
        keys.check_key(ORG, b"x")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "prefix",
    [
        f"{ORG}/datasets/{DATASET}/",
        f"{ORG}/datasets/{DATASET}",
        f"{ORG}/",
    ],
)
def test_a_prefix_of_the_organization_is_normalised_to_end_in_a_slash(
    prefix: str,
) -> None:
    assert keys.check_prefix(ORG, prefix).endswith("/")


@pytest.mark.parametrize(
    "prefix",
    [
        f"{OTHER_ORG}/",
        f"{OTHER_ORG}/datasets/",
        "",
        "/",
        f"{ORG}",
        f"{ORG}/../",
        f"{ORG}/a//",
        f"{ORG}x/",
        str(ORG)[:-1] + "/",
        f"{ORG}/．/",
    ],
)
def test_a_prefix_outside_the_organization_or_malformed_is_refused(prefix: str) -> None:
    with pytest.raises(InvalidKeyError):
        keys.check_prefix(ORG, prefix)
