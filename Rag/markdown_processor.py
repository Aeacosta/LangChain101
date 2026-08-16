"""Processes Markdown files and extracts text chunks.

Mirrors PDFProcessor but reads .md files instead of PDFs.
Each chunk is labelled with the nearest H2/H3 section heading.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from RAG.rag_config import RAGConfig

_logger = logging.getLogger("markdown_processor")

# Matches Markdown ATX headings: ## Section or ### Sub-section
_HEADING_RE = re.compile(r'^#{1,3}\s+(.+)', re.MULTILINE)


class MarkdownProcessor:
    """Reads every .md file in a folder and returns overlapping text chunks."""

    def __init__(self, config: RAGConfig, logger=None) -> None:
        self.config = config
        self._log = _logger
        self._folder = Path(config.pdf_folder)   # pdf_folder is the generic source folder

    def process_all_markdown(self) -> list[dict[str, str]]:
        """Return chunks from every .md file found in the configured folder."""
        documents: list[dict[str, str]] = []

        if not self._folder.exists():
            self._log.warning("Folder %s does not exist", self._folder)
            return documents

        md_files = sorted(self._folder.glob("**/*.md"))
        if not md_files:
            self._log.warning("No .md files found in %s", self._folder)
            return documents

        self._log.info("Processing %d Markdown file(s)...", len(md_files))

        for path in md_files:
            try:
                chunks = self._chunk_file(path)
                documents.extend(chunks)
                self._log.debug("  %s -> %d chunks", path.name, len(chunks))
            except Exception as exc:
                self._log.error("Error processing %s: %s", path.name, exc)

        return documents

    # ------------------------------------------------------------------

    def _current_heading(self, text: str) -> str:
        """Return the last heading found in *text*, or empty string."""
        headings = _HEADING_RE.findall(text)
        return headings[-1].strip() if headings else ""

    def _chunk_file(self, path: Path) -> list[dict[str, str]]:
        """Split a single Markdown file into overlapping chunks."""
        content = path.read_text(encoding="utf-8")

        chunk_size = self.config.chunk_size
        overlap    = self.config.chunk_overlap
        chunks: list[dict[str, str]] = []
        current_heading = ""

        for i in range(0, len(content), chunk_size - overlap):
            chunk = content[i : i + chunk_size]
            if not chunk.strip():
                continue

            detected = self._current_heading(chunk)
            if detected:
                current_heading = detected

            chunks.append({
                "id":      f"{path.name}_chunk_{i}",
                "text":    chunk,
                "source":  path.stem,
                "chapter": current_heading,
            })

        return chunks
