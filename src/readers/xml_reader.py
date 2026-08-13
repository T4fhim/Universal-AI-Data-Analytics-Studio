# File: src/readers/xml_reader.py
"""Reads XML files into a Dataset by detecting repeated sibling elements as rows.

XML has no single canonical "this is a table" shape the way JSON's
array-of-objects does — a well-formed XML document is a tree, and
whether that tree represents tabular data depends entirely on whether
it contains a meaningful pattern of *repeated sibling elements* (e.g.
``<product>...</product>`` appearing multiple times under
``<catalog>``). This reader's core strategy: find the child tag name
that repeats most often directly under the document root, treat each
occurrence as one row, and flatten that element's attributes and child
elements into columns.

This is deliberately narrower than a general XML-to-table converter.
It does not attempt to handle multiple different repeating structures
within one document, arbitrary XPath-selectable row sources, or deeply
irregular trees where no single tag dominates. If the document has no
clear repeating-element pattern at the root's direct children, this
reader raises :class:`~src.core.exceptions.ReaderError` rather than
guessing at a tabular interpretation of data that may not be tabular
at all — the same posture :class:`~src.readers.json_reader.JsonReader`
takes for JSON shapes it does not recognize as tabular (a single
non-columnar object, for instance). This is different from
:class:`~src.readers.pdf_reader.PdfReader`'s and
:class:`~src.readers.word_reader.WordReader`'s "zero tables is a valid
outcome" contract: an XML document either has a detectable repeating
structure or it does not, and "does not" is closer to "this content
was never tabular" than to "this is a valid document that happens to
have none."

Uses ``lxml`` rather than the standard library's ``xml.etree``, for
two concrete reasons: better tolerance of minor malformation during
parsing (via a configurable recovery mode, not used by default here
but available if a future milestone wants it), and access to each
element's attributes and children through a more ergonomic API when
flattening a row's content into columns.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd
from lxml import etree

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_XML_EXTENSIONS = {".xml"}

# The most-repeated direct child tag must appear at least this many
# times to be treated as a row pattern. A tag appearing only once
# cannot be "repeated" by definition (Counter would report it as the
# most common with count 1, which is not a meaningful signal of
# tabular structure — a document root with several different
# once-each children, like <config>, is exactly this case).
_MINIMUM_REPEAT_COUNT = 2


class XmlReader(BaseReader):
    """Reads XML files by detecting the dominant repeated child element as the row unit."""

    SUPPORTED_EXTENSIONS = _XML_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _XML_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read ``path``, treating the most-repeated root-level child element as rows.

        Args:
            path: The XML file to read.
            table_name: Accepted for interface uniformity with
                :meth:`~src.readers.base_reader.BaseReader.read`, but
                ignored — this reader has exactly one detection
                strategy and does not offer alternative "tables" to
                choose between within a single file. See
                :meth:`~src.readers.csv_reader.CsvReader.read`'s
                docstring for the fuller reasoning behind readers
                accepting-but-ignoring this parameter.

        Raises:
            ReaderError: If the file does not exist, is not
                well-formed XML, or has no child tag repeated at least
                :data:`_MINIMUM_REPEAT_COUNT` times directly under the
                root element.
        """
        if not path.exists():
            raise ReaderError(f"XML file does not exist: {path}")

        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError as exc:
            raise ReaderError(f"File {path} is not well-formed XML: {exc}") from exc

        root = tree.getroot()
        row_tag = cls._find_row_tag(root, path)
        row_elements = root.findall(row_tag)

        warnings: list[str] = []
        records = []
        for element in row_elements:
            record, element_warnings = cls._element_to_record(element)
            records.append(record)
            warnings.extend(element_warnings)

        dataframe = pd.DataFrame(records)

        # Deduplicate warnings that would otherwise repeat once per
        # row (e.g. the same nested-structure note firing for every
        # element that has one) — a single mention is all the user
        # needs, not one copy per affected row.
        unique_warnings = list(dict.fromkeys(warnings))

        _logger.info(
            "Read XML file %s (row tag: <%s>): %d rows, %d columns, "
            "%d warning(s).",
            path,
            row_tag,
            len(dataframe),
            len(dataframe.columns),
            len(unique_warnings),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="xml",
            source_path=path,
            read_warnings=unique_warnings,
        )

    @classmethod
    def _find_row_tag(cls, root, path: Path) -> str:
        """Return the tag name of the most-repeated direct child of ``root``.

        Raises:
            ReaderError: If no direct child tag repeats at least
                :data:`_MINIMUM_REPEAT_COUNT` times — meaning this
                document has no detectable row pattern at the root
                level.
        """
        direct_child_tags = [child.tag for child in root]
        if not direct_child_tags:
            raise ReaderError(
                f"{path} has a root element with no children at all; "
                f"there is no content to read as rows."
            )

        tag_counts = Counter(direct_child_tags)
        most_common_tag, count = tag_counts.most_common(1)[0]

        if count < _MINIMUM_REPEAT_COUNT:
            distinct_tags = ", ".join(sorted(tag_counts.keys()))
            raise ReaderError(
                f"{path} has no repeated element pattern directly "
                f"under its root — no child tag appears more than "
                f"once (found: {distinct_tags}). This reader requires "
                f"a repeating element (e.g. multiple <record> tags) "
                f"to identify what a 'row' should be; a document "
                f"structured this way has no clear tabular "
                f"interpretation."
            )

        return most_common_tag

    @classmethod
    def _element_to_record(cls, element) -> tuple[dict, list[str]]:
        """Flatten one row element's attributes, children, and text into a flat dict.

        Attributes become columns named directly after the attribute
        (e.g. ``id="1"`` becomes column ``id``). Child elements with
        no children of their own become columns named after their tag
        (e.g. ``<name>Widget</name>`` becomes column ``name`` with
        value ``"Widget"``). A child element that itself has further
        nested children is flattened one level using a dotted name
        (matching the convention
        :class:`~src.readers.json_reader.JsonReader` already
        established for nested JSON), and produces a warning the
        first time it's encountered, for the same reason
        ``JsonReader`` warns on nested flattening: the resulting
        column names don't map one-to-one back to the original
        structure, which is worth the user knowing.
        """
        record: dict = {}
        warnings: list[str] = []

        for attribute_name, attribute_value in element.attrib.items():
            record[attribute_name] = attribute_value

        for child in element:
            if len(child) > 0:
                # Child has its own children: flatten one level deep
                # with a dotted name, same convention as JsonReader.
                for grandchild in child:
                    column_name = f"{_local_tag(child)}.{_local_tag(grandchild)}"
                    record[column_name] = grandchild.text
                warnings.append(
                    "Some elements contained further nested child "
                    "elements; these were flattened into dotted "
                    "column names (e.g. 'address.city'), matching how "
                    "nested JSON is handled by this project's JSON "
                    "reader."
                )
            else:
                record[_local_tag(child)] = child.text

        if element.text and element.text.strip() and len(element) == 0 and not element.attrib:
            # An element with direct text content and no attributes or
            # children at all (e.g. <product>Widget</product> with no
            # sub-structure) — its own text becomes the record itself
            # rather than a named column, since there is no
            # attribute/child name to attach it to.
            record["value"] = element.text.strip()

        return record, warnings


def _local_tag(element) -> str:
    """Return an element's tag name without an XML namespace prefix, if present.

    ``lxml`` represents a namespaced tag as ``{namespace-uri}tagname``
    — stripping the namespace portion keeps generated column names
    readable (``city`` rather than
    ``{http://example.com/ns}city``). This project's readers do not
    currently need to disambiguate between same-named elements from
    different namespaces within one document; if that becomes a real
    requirement, this function is the one place that decision would
    need to change.
    """
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)
