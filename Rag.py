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

    def find_documents(self, text_to_find: str):
        return self.vector_store.search(text_to_find)
