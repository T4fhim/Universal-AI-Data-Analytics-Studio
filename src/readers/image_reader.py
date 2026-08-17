# File: src/readers/image_reader.py
"""Extracts tabular data from images via OCR, clustering recognized words into rows and columns.

:class:`ImageReader` is fundamentally different from every other
reader in this project, and that difference needs to be stated plainly
rather than glossed over: **OCR output is not verifiable against
ground truth the way every other reader's output is.** A CSV reader's
correctness can be checked against the file's actual bytes. This
reader's correctness depends on ``tesseract``'s ability to correctly
recognize characters in an image — a fundamentally probabilistic
process that can misread text, especially on low-resolution, skewed,
or stylistically unusual source images. This reader surfaces
``tesseract``'s own per-word confidence scores (see
:data:`_LOW_CONFIDENCE_THRESHOLD` below) as warnings, but a low
confidence score does not guarantee a wrong answer, and a high one
does not guarantee a correct one — it is the best available signal,
not a certainty.

**Strategy**: ``tesseract`` (via ``pytesseract.image_to_data``) returns
each recognized word's text, confidence, and pixel-position bounding
box. This reader does not attempt to use ``tesseract``'s own built-in
table-structure detection modes (which exist but are tuned for
specific, well-defined table layouts); instead, it clusters
recognized words into rows by grouping words with similar vertical
(``top``) position, then orders words within each row by horizontal
(``left``) position to approximate column order. This is a real,
working approach for images where text is arranged in a roughly
grid-aligned layout (the common case for a table rendered as an image
or screenshot) but is not a substitute for genuine table-structure
recognition — an image with curved, rotated, or highly irregular text
placement will likely produce a poor or unusable clustering, and this
reader does not attempt to detect that case and warn about it
specifically, since distinguishing "genuinely tabular but imperfectly
clustered" from "not tabular at all" from pixel positions alone is a
harder problem than this milestone's scope covers.

**Column alignment across rows is approximate, not guaranteed.** This
reader does not attempt to align words into a consistent, named column
structure the way every text-based reader in this project does — a
CSV's header row explicitly names each column, but an OCR'd image has
no equivalent unless the image happens to contain literal header text
that this reader could not reliably distinguish from data. Columns are
therefore numbered positionally (``Column 1, Column 2, ...``) based on
left-to-right word order within the row with the most detected words,
and shorter rows are padded — this is an honest, working
approximation, not a claim of semantic column identity.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytesseract
from PIL import Image

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

# tesseract reports confidence 0-100 per recognized word; -1 for
# non-text detections (this reader filters those out entirely, not
# just low-confidence ones — a -1 confidence isn't "uncertain text",
# it's "not identified as text at all").
_LOW_CONFIDENCE_THRESHOLD = 60

# Words on the same visual row will not have byte-for-byte identical
# `top` pixel values even in a cleanly rendered image (font rendering,
# anti-aliasing, and OCR's own bounding-box estimation all introduce
# small variance) — found necessary by testing against a real
# rendered image, where words on the same intended row differed by a
# few pixels in reported `top` position. Two words are considered
# part of the same row if their `top` values differ by no more than
# this many pixels.
_ROW_CLUSTER_TOLERANCE_PX = 15


class ImageReader(BaseReader):
    """Extracts tabular data from images via OCR (tesseract), clustering words into rows/columns."""

    SUPPORTED_EXTENSIONS = _IMAGE_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _IMAGE_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Run OCR on the image at ``path`` and cluster the result into rows and columns.

        Args:
            path: The image to read.
            table_name: Accepted for interface uniformity with
                :meth:`~src.readers.base_reader.BaseReader.read`, but
                ignored — this reader has exactly one extraction
                strategy per image. See
                :meth:`~src.readers.csv_reader.CsvReader.read`'s
                docstring for the fuller reasoning.

        Raises:
            ReaderError: If the file does not exist, cannot be opened
                as an image, or OCR detects no text at all in the
                image (a genuinely blank or non-textual image is a
                valid input with nothing to extract — this is raised
                as an error rather than treated the same as
                :class:`~src.readers.pdf_reader.PdfReader`'s
                zero-tables case, since an image is a single object
                with no analogous "list what's available first"
                step — there is nothing to list, only "OCR found
                text" or "it didn't").
        """
        if not path.exists():
            raise ReaderError(f"Image file does not exist: {path}")

        try:
            image = Image.open(path)
        except Exception as exc:
            raise ReaderError(f"Failed to open {path} as an image: {exc}") from exc

        try:
            ocr_data = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT
            )
        except Exception as exc:
            raise ReaderError(f"OCR failed on {path}: {exc}") from exc

        words = cls._extract_valid_words(ocr_data)
        if not words:
            raise ReaderError(
                f"OCR found no text in {path}. If this image contains "
                f"text that should be readable, check its resolution "
                f"and contrast — very small, low-contrast, or heavily "
                f"stylized text is a common cause of OCR failure."
            )

        rows = cls._cluster_into_rows(words)
        dataframe = cls._rows_to_dataframe(rows)

        warnings: list[str] = []
        low_confidence_count = sum(
            1 for w in words if w["conf"] < _LOW_CONFIDENCE_THRESHOLD
        )
        if low_confidence_count > 0:
            warnings.append(
                f"{low_confidence_count} of {len(words)} recognized "
                f"word(s) had low OCR confidence (below "
                f"{_LOW_CONFIDENCE_THRESHOLD}%) and may be inaccurate. "
                f"OCR results are not guaranteed to be correct — "
                f"review the extracted data against the original "
                f"image before relying on it."
            )
        else:
            # Even with no low-confidence words, OCR is fundamentally
            # not verifiable the way this project's other readers'
            # output is — this general caveat is recorded every time,
            # not just when confidence is measurably low, so the user
            # is never left assuming an absence of low-confidence
            # warnings means a guarantee of correctness.
            warnings.append(
                "This data was extracted via OCR and has not been "
                "verified against the source image's actual content. "
                "Review the extracted data before relying on it."
            )

        _logger.info(
            "OCR'd image %s: %d rows, %d columns, %d/%d words below "
            "confidence threshold.",
            path,
            len(dataframe),
            len(dataframe.columns),
            low_confidence_count,
            len(words),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="image_ocr",
            source_path=path,
            read_warnings=warnings,
        )

    @classmethod
    def _extract_valid_words(cls, ocr_data: dict) -> list[dict]:
        """Filter tesseract's raw output down to genuinely detected words.

        Discards entries with empty/whitespace-only text (tesseract's
        output includes many non-word bounding boxes — lines, blocks,
        paragraphs — that share the same flat dict structure as actual
        words but have no text content) and entries with confidence
        ``-1`` (tesseract's marker for "not a text detection at all",
        distinct from a low-but-real confidence score).
        """
        words = []
        for i in range(len(ocr_data["text"])):
            text = ocr_data["text"][i].strip()
            confidence = ocr_data["conf"][i]
            if text and confidence >= 0:
                words.append(
                    {
                        "text": text,
                        "left": ocr_data["left"][i],
                        "top": ocr_data["top"][i],
                        "conf": confidence,
                    }
                )
        return words

    @classmethod
    def _cluster_into_rows(cls, words: list[dict]) -> list[list[dict]]:
        """Group words into rows by proximity in vertical (`top`) position.

        Words are first sorted by `top`, then grouped: each word joins
        the current row if its `top` is within
        :data:`_ROW_CLUSTER_TOLERANCE_PX` of the row's first word;
        otherwise it starts a new row. Within each resulting row,
        words are ordered left-to-right by `left` position, which
        approximates column order for a roughly grid-aligned source
        image.
        """
        sorted_words = sorted(words, key=lambda w: w["top"])

        rows: list[list[dict]] = []
        current_row: list[dict] = []
        current_row_top: int | None = None

        for word in sorted_words:
            if (
                current_row_top is None
                or abs(word["top"] - current_row_top) <= _ROW_CLUSTER_TOLERANCE_PX
            ):
                current_row.append(word)
                if current_row_top is None:
                    current_row_top = word["top"]
            else:
                rows.append(sorted(current_row, key=lambda w: w["left"]))
                current_row = [word]
                current_row_top = word["top"]

        if current_row:
            rows.append(sorted(current_row, key=lambda w: w["left"]))

        return rows

    @classmethod
    def _rows_to_dataframe(cls, rows: list[list[dict]]) -> pd.DataFrame:
        """Convert clustered rows into a DataFrame with positional column names.

        The row with the most words determines the column count;
        shorter rows are padded with empty strings. Column names are
        positional (``Column 1``, ``Column 2``, ...) rather than drawn
        from any row's content — see the module docstring for why
        this reader does not attempt to identify a semantic header
        row the way text-based readers do.
        """
        max_column_count = max(len(row) for row in rows)
        column_names = [f"Column {i + 1}" for i in range(max_column_count)]

        records = []
        for row in rows:
            row_texts = [word["text"] for word in row]
            padded = row_texts + [""] * (max_column_count - len(row_texts))
            records.append(padded)

        return pd.DataFrame(records, columns=column_names)
