---
title: "XML Reader"
anchors:
  - readers.xml
---

# XML Reader

`uadas_core.readers.xml_reader.XmlReader` -- `.xml`.

XML has no single canonical "this is a table" shape the way JSON's array-of-objects does. This
reader's strategy: find the child tag name that repeats most often directly under the document
root, treat each occurrence as one row, and flatten that element's attributes and child
elements into columns.

This is deliberately narrower than a general XML-to-table converter: it does not handle
multiple different repeating structures within one document, arbitrary XPath-selectable row
sources, or deeply irregular trees where no single tag dominates. A document with no clear
repeating-element pattern at the root's direct children is rejected with a message, rather than
forced into a table it was never meant to be -- unlike the PDF/Word readers' "zero tables is
valid" contract, an XML document either has a detectable repeating structure or it does not,
and "does not" here is closer to "this content was never tabular."

Uses `lxml` for better tolerance of minor malformation and a more ergonomic attribute/child API
than the standard library's `xml.etree`.

Single-table.
