from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from RAG.rag_config import RAGConfig
from RAG.pdf_processor import PDFProcessor
from RAG.vector_store import VectorStore

class RagCore:
    def __init__(self):
        config = RAGConfig()
        pdf_processor = PDFProcessor(config=config)
        chunks = pdf_processor.process_all_pdfs()
        self.vector_store = VectorStore(config=config)
        if chunks:
            self.vector_store.add_documents(chunks)
    

    def find_documents(self, text_to_find : str):
        return self.vector_store.search(text_to_find)
