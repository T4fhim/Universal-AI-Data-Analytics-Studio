---
title: "Image (OCR) Reader"
anchors:
  - readers.image
---

# Image (OCR) Reader

`src.readers.image_reader.ImageReader` -- `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.tif`.

Fundamentally different from every other reader: **OCR output is not verifiable against ground
truth the way every other reader's output is.** A CSV reader's correctness can be checked
against the file's actual bytes; this reader's correctness depends on `tesseract`'s ability to
correctly recognize characters in an image -- a probabilistic process that can misread text,
especially on low-resolution, skewed, or stylistically unusual source images. Per-word
confidence scores are surfaced as warnings, but a low score does not guarantee a wrong answer,
and a high one does not guarantee a correct one -- it is the best available signal, not a
certainty.

## Strategy

`tesseract` (via `pytesseract.image_to_data`) returns each recognized word's text, confidence,
and pixel position. Rather than tesseract's own table-structure detection (tuned for specific,
well-defined layouts), this reader clusters recognized words into rows by grouping words with
similar vertical position, then orders words within each row by horizontal position to
approximate column order. This works for images where text is roughly grid-aligned (a table
rendered as an image or screenshot) but is not a substitute for genuine table-structure
recognition -- curved, rotated, or highly irregular text placement will likely produce a poor
or unusable clustering.

**Column alignment is approximate, not guaranteed.** There is no header row to name columns
the way a CSV's first line does, so columns are numbered positionally (`Column 1`, `Column 2`,
...) based on left-to-right word order in the row with the most detected words, with shorter
rows padded -- an honest approximation, not a claim of semantic column identity.

Single-table.
