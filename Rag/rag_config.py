"""Configuración del sistema RAG."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RAGConfig:
	"""Configuración del sistema RAG."""
	pdf_folder: str = "Documentos"
	chroma_db_path: str = ".chroma"
	collection_name: str = "Documentacion"
	chunk_size: int = 1000              # Tamaño de cada chunk (caracteres)
	chunk_overlap: int = 200            # Solapamiento entre chunks
	top_k: int = 5                      # Documentos recuperados por búsqueda
	embedding_model: str = "all-MiniLM-L6-v2"  # Modelo de embeddings
	
	def __post_init__(self):
		"""Carga configuración desde variables de entorno."""
		self.chunk_size = int(os.getenv("RAG_CHUNK_SIZE", self.chunk_size))
		self.chunk_overlap = int(os.getenv("RAG_CHUNK_OVERLAP", self.chunk_overlap))
		self.top_k = int(os.getenv("RAG_TOP_K", self.top_k))
		self.embedding_model = os.getenv("RAG_EMBEDDING_MODEL", self.embedding_model)
		self.pdf_folder = os.getenv("RAG_PDF_FOLDER", self.pdf_folder)
		self.chroma_db_path = os.getenv("RAG_CHROMA_DB_PATH", self.chroma_db_path)

# Made with Bob