# File: tests/readers/test_xml_reader_hardening.py
"""The XML reader must not resolve external or recursive entities (a parser-hardening review item).

Why: ``lxml``'s default parser resolves entities, including ``SYSTEM`` entities that name a local
file, so an uploaded ``.xml`` could put ``/etc/passwd`` (or any file the process can read) into a
cell of the table the user then sees (XXE). The reader now builds its own parser with entity
resolution, DTD loading and network access off and the huge-tree limits on. In the web product
the reader runs in the sandbox child (itself unable to reach most of the host) -- this is the
defence at the parsing layer, and it protects the desktop use of the core too.

Each rejection has an accepted twin: the same shape of document without the attack parses into the
expected table, so a reader that refused every XML file could not pass.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from pathlib import Path

import pytest

from uadas_core.core.exceptions import ReaderError
from uadas_core.readers.xml_reader import XmlReader

SECRET = "TOP-SECRET-MARKER-9f3b7c"


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def every_cell(dataset) -> str:  # type: ignore[no-untyped-def]
    frame = dataset.dataframe
    cells = [str(value) for column in frame.columns for value in frame[column]]
    return " ".join([*map(str, frame.columns), *cells, *dataset.read_warnings])


def test_the_reader_pins_its_parsers_safety_settings_instead_of_trusting_lxml_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # lxml 5+ happens to default to "internal" entity resolution; older versions resolved external
    # entities. The reader must not depend on which lxml it is installed beside.
    from lxml import etree

    from uadas_core.readers import xml_reader

    seen: list[dict[str, object]] = []
    real = etree.XMLParser

    def recording(*args: object, **kwargs: object) -> object:
        seen.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(xml_reader.etree, "XMLParser", recording)
    path = write(tmp_path, "p.xml", "<r><row><a>1</a></row><row><a>2</a></row></r>")
    XmlReader.read(path)
    assert seen, "the reader parsed with lxml's default parser"
    assert seen[0] == {
        "resolve_entities": False,
        "no_network": True,
        "load_dtd": False,
        "huge_tree": False,
    }


def test_a_normal_document_parses_into_rows(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "ok.xml",
        "<items><item id='1'><name>widget</name></item>"
        "<item id='2'><name>gadget</name></item></items>",
    )
    dataset = XmlReader.read(path)
    assert dataset.dataframe["name"].tolist() == ["widget", "gadget"]
    assert dataset.dataframe["id"].tolist() == ["1", "2"]


def test_a_document_with_an_internal_dtd_but_no_attack_still_parses(
    tmp_path: Path,
) -> None:
    path = write(
        tmp_path,
        "dtd.xml",
        "<?xml version='1.0'?><!DOCTYPE items [<!ELEMENT items ANY>]>"
        "<items><item><name>a</name></item><item><name>b</name></item></items>",
    )
    assert XmlReader.read(path).dataframe["name"].tolist() == ["a", "b"]


def test_an_external_file_entity_never_reaches_the_table(tmp_path: Path) -> None:
    secret = write(tmp_path, "secret.txt", SECRET)
    attack = write(
        tmp_path,
        "xxe.xml",
        f"<?xml version='1.0'?><!DOCTYPE r [<!ENTITY x SYSTEM '{secret.as_uri()}'>]>"
        "<r><row><a>&x;</a></row><row><a>2</a></row></r>",
    )
    try:
        dataset = XmlReader.read(attack)
    except ReaderError:
        return  # refusing the document outright is also acceptable
    assert SECRET not in every_cell(dataset)


def test_a_parameter_entity_pointing_at_a_file_is_not_loaded(tmp_path: Path) -> None:
    secret = write(tmp_path, "secret2.txt", SECRET)
    attack = write(
        tmp_path,
        "xxe2.xml",
        f"<?xml version='1.0'?><!DOCTYPE r [<!ENTITY % p SYSTEM '{secret.as_uri()}'>%p;]>"
        "<r><row><a>1</a></row><row><a>2</a></row></r>",
    )
    try:
        dataset = XmlReader.read(attack)
    except ReaderError:
        return
    assert SECRET not in every_cell(dataset)


def test_an_exponential_entity_bomb_is_neither_expanded_nor_slow(
    tmp_path: Path,
) -> None:
    levels = "".join(
        f"<!ENTITY e{i} '{f'&e{i - 1};' * 10}'>" if i else "<!ENTITY e0 'lol-lol-lol'>"
        for i in range(9)
    )
    bomb = write(
        tmp_path,
        "bomb.xml",
        f"<?xml version='1.0'?><!DOCTYPE r [{levels}]>"
        "<r><row><a>&e8;</a></row><row><a>fine</a></row></r>",
    )
    started = time.monotonic()
    try:
        dataset = XmlReader.read(bomb)
        assert max(len(c) for c in every_cell(dataset).split()) < 10_000
    except ReaderError:
        pass
    assert time.monotonic() - started < 10


def test_an_external_dtd_url_is_never_fetched(tmp_path: Path) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(0.5)
    port = server.getsockname()[1]
    connections: list[int] = []

    def accept() -> None:
        try:
            connection, _ = server.accept()
            connections.append(1)
            connection.close()
        except OSError:
            pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    attack = write(
        tmp_path,
        "net.xml",
        f"<?xml version='1.0'?><!DOCTYPE r SYSTEM 'http://127.0.0.1:{port}/x.dtd'>"
        "<r><row><a>1</a></row><row><a>2</a></row></r>",
    )
    with contextlib.suppress(ReaderError):
        XmlReader.read(attack)
    thread.join(timeout=2)
    server.close()
    assert connections == []


@pytest.mark.parametrize("document", ["<r>", "not xml at all", ""])
def test_malformed_xml_is_still_a_reader_error(tmp_path: Path, document: str) -> None:
    with pytest.raises(ReaderError):
        XmlReader.read(write(tmp_path, "bad.xml", document))
