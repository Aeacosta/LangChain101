"""XTP-specific RAG core.

Mirrors RagCore (Rag.py) but uses:
  - folder   : DocumentosXTP   (Markdown manuals)
  - collection: XTP_Manual      (isolated from the code-smell PDFs)

Usage
-----
from RAG.xtp_rag import XTPRagCore

rag = XTPRagCore()
result = rag.find_documents("Bin2Bin transition SB_1001 to SB_4001")
"""

from __future__ import annotations

from RAG.rag_config import RAGConfig
from RAG.markdown_processor import MarkdownProcessor
from RAG.vector_store import VectorStore
from Helpers.Logger import AgentLogger


class XTPRagCore:
    """RAG over the XTP Markdown manuals stored in DocumentosXTP/."""

    def __init__(self, logger: AgentLogger | None = None) -> None:
        self._log = logger or AgentLogger(name="xtp_rag")

        config = RAGConfig(
            pdf_folder="DocumentosXTP",
            collection_name="XTP_Manual",
        )

        processor = MarkdownProcessor(config=config, logger=self._log)
        chunks    = processor.process_all_markdown()

        self.vector_store = VectorStore(config=config, logger=self._log)
        if chunks:
            self.vector_store.add_documents(chunks)

    def find_documents(self, query: str) -> str:
        """Search the XTP manual and return the top match as an APA-style citation.

        Returns an empty string when nothing is found.
        """
        results = self.vector_store.search(query)
        if not results:
            return ""

        top     = results[0]
        source  = top.get("source", "Unknown")
        chapter = top.get("chapter", "")
        chapter_part = f" {chapter}." if chapter else ""
        return f"{source} (n.d.).{chapter_part}"
