from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from RAG.rag_config import RAGConfig
from RAG.pdf_processor import PDFProcessor
from RAG.vector_store import VectorStore
from Helpers.Logger import AgentLogger


class RagCore:
    def __init__(self, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="rag_agent")
        config = RAGConfig()
        pdf_processor = PDFProcessor(config=config, logger=self._log)
        chunks = pdf_processor.process_all_pdfs()
        self.vector_store = VectorStore(config=config, logger=self._log)
        if chunks:
            self.vector_store.add_documents(chunks)

    def find_documents(self, text_to_find: str) -> str:
        """Search the vector store and return the top result formatted as an
        APA-style reference string the LLM can copy directly into ragReference.

        Format: Title (n.d.). Chapter heading.
        """
        results = self.vector_store.search(text_to_find)
        if not results:
            return ""

        # Use the closest match (first result, lowest cosine distance).
        top = results[0]
        source = top.get("source", "Unknown")
        chapter = top.get("chapter", "")

        # Build APA-style reference: Title (n.d.). Chapter.
        chapter_part = f" {chapter}." if chapter else ""
        apa = f"{source} (n.d.).{chapter_part}"
        return apa
