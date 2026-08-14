"""PDF -> addressable text lines.

The only module that imports pdfplumber. Everything downstream works on
`TextLine`, so swapping in OCR (Phase 3) or an LLM extractor (Phase 2) means
producing TextLines — or bypassing this stage entirely and emitting canonical
models directly.

Each line keeps its page and line number so evidence can cite "page 1, line 12".
"""

from __future__ import annotations

from dataclasses import dataclass

import pdfplumber

from .errors import ExtractionError

MAX_PAGES = 20


@dataclass(frozen=True)
class TextLine:
    page: int
    line_no: int
    text: str

    @property
    def locator(self) -> str:
        return f"page {self.page}, line {self.line_no}"


def read_lines(data: bytes) -> list[TextLine]:
    """Extract non-empty text lines from a PDF byte string."""
    if not data:
        raise ExtractionError("EMPTY_FILE", "The uploaded file is empty.")
    if not data.startswith(b"%PDF"):
        raise ExtractionError(
            "NOT_A_PDF",
            "The uploaded file is not a PDF.",
            ["Expected the file to begin with the %PDF header."],
        )

    import io

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                raise ExtractionError("NO_PAGES", "The PDF contains no pages.")

            lines: list[TextLine] = []
            for page_index, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
                text = page.extract_text() or ""
                for line_index, raw in enumerate(text.splitlines(), start=1):
                    cleaned = " ".join(raw.split())
                    if cleaned:
                        lines.append(TextLine(page_index, line_index, cleaned))
    except ExtractionError:
        raise
    except Exception as exc:  # pdfminer raises a wide variety of parse errors
        raise ExtractionError(
            "UNREADABLE_PDF",
            "The PDF could not be read. It may be corrupt or password-protected.",
            [f"{type(exc).__name__}: {exc}"],
        ) from exc

    if not lines:
        raise ExtractionError(
            "NO_TEXT",
            "No text layer was found in this PDF.",
            [
                "Phase 1 supports text-based PDFs only. "
                "Scanned or image-only documents require the OCR pipeline planned for Phase 3."
            ],
        )
    return lines
