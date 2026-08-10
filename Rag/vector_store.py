"""Almacén vectorial usando Chroma."""

from __future__ import annotations

import logging

try:
	import chromadb
except ImportError:
	chromadb = None

from RAG.rag_config import RAGConfig

_logger = logging.getLogger("vector_store")


class VectorStore:
	"""Almacén vectorial usando Chroma."""

	def __init__(self, config: RAGConfig, logger=None):
		if chromadb is None:
			raise ImportError("chromadb no está instalado. Instala con: pip install chromadb")

		self.config = config
		# If an AgentLogger is injected its handlers are already wired to
		# the "vector_store" child logger via AgentLogger.__init__.
		self._log = _logger
		self.client = chromadb.PersistentClient(path=config.chroma_db_path)
		self.collection = self.client.get_or_create_collection(
			name=config.collection_name,
			metadata={"hnsw:space": "cosine"},
		)
		self._log.info(
			"VectorStore listo — colección=%r, path=%s",
			config.collection_name,
			config.chroma_db_path,
		)

	def add_documents(self, documents: list[dict[str, str]]) -> int:
		"""Agrega documentos al almacén vectorial."""
		if not documents:
			return 0

		# Chroma genera embeddings automáticamente
		ids = [doc["id"] for doc in documents]
		documents_text = [doc["text"] for doc in documents]
		metadatas = [{"source": doc.get("source", "unknown")} for doc in documents]

		self.collection.upsert(
			ids=ids,
			documents=documents_text,
			metadatas=metadatas,
		)
		self._log.info("Indexados %d documentos en la colección %r", len(documents), self.config.collection_name)

		return len(documents)

	def search(self, query: str) -> list[dict[str, str]]:
		"""Busca documentos similares."""
		results = self.collection.query(
			query_texts=[query],
			n_results=self.config.top_k,
		)

		documents = []
		if results["documents"] and len(results["documents"]) > 0:
			for i, doc in enumerate(results["documents"][0]):
				metadata = results["metadatas"][0][i] if results["metadatas"] else {}
				documents.append({
					"text": doc,
					"source": metadata.get("source", "unknown"),
					"distance": float(results["distances"][0][i]) if results["distances"] else 0,
				})
		self._log.debug("Resultados encontrados: %d", len(documents))

		return documents
	
	def clear(self):
		"""Limpia la colección."""
		self.client.delete_collection(name=self.config.collection_name)
		self.collection = self.client.get_or_create_collection(
			name=self.config.collection_name,
			metadata={"hnsw:space": "cosine"}
		)

# Made with Bob