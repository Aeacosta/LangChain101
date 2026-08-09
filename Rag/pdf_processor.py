"""Procesa PDFs y extrae texto."""

from __future__ import annotations

from pathlib import Path

try:
	from PyPDF2 import PdfReader
except ImportError:
	PdfReader = None

from RAG.rag_config import RAGConfig


class PDFProcessor:
	"""Procesa PDFs y extrae texto."""
	
	def __init__(self, config: RAGConfig):
		if PdfReader is None:
			raise ImportError("PyPDF2 no está instalado. Instala con: pip install PyPDF2")
		
		self.config = config
		self.pdf_folder = Path(config.pdf_folder)
	
	def process_all_pdfs(self) -> list[dict[str, str]]:
		"""Procesa todos los PDFs en la carpeta y retorna chunks de texto."""
		documents = []
		
		if not self.pdf_folder.exists():
			print("Carpeta %s no existe", self.config.pdf_folder)
			return documents
		
		pdf_files = list(self.pdf_folder.glob("*.pdf"))
		if not pdf_files:
			print("No se encontraron PDFs en %s", self.config.pdf_folder)
			return documents
		
		print("Procesando %d PDF(s)...", len(pdf_files))
		
		for pdf_path in pdf_files:
			try:
				chunks = self._extract_chunks_from_pdf(pdf_path)
				documents.extend(chunks)
				print("  %s -> %d chunks", pdf_path.name, len(chunks))
			except Exception as e:
				self._log._logger.error("Error procesando %s: %s", pdf_path.name, e)
		
		return documents
	
	def _extract_chunks_from_pdf(self, pdf_path: Path) -> list[dict[str, str]]:
		"""Extrae chunks de un PDF."""
		reader = PdfReader(pdf_path)
		text = ""
		
		for page in reader.pages:
			text += page.extract_text()
		
		# Crear chunks
		chunks = []
		chunk_size = self.config.chunk_size
		overlap = self.config.chunk_overlap
		
		for i in range(0, len(text), chunk_size - overlap):
			chunk = text[i:i + chunk_size]
			if chunk.strip():
				chunk_id = f"{pdf_path.name}_chunk_{i}"
				chunks.append({
					"id": chunk_id,
					"text": chunk,
					"source": pdf_path.name
				})
		
		return chunks