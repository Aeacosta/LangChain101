"""Procesa PDFs y extrae texto."""

from __future__ import annotations

import logging
import re
from pathlib import Path

try:
	from PyPDF2 import PdfReader
except ImportError:
	PdfReader = None

from RAG.rag_config import RAGConfig

_logger = logging.getLogger("pdf_processor")


class PDFProcessor:
	"""Procesa PDFs y extrae texto."""

	def __init__(self, config: RAGConfig, logger=None):
		if PdfReader is None:
			raise ImportError("PyPDF2 no está instalado. Instala con: pip install PyPDF2")

		self.config = config
		self.pdf_folder = Path(config.pdf_folder)
		# If an AgentLogger is injected its handlers are already wired to
		# the "pdf_processor" child logger via AgentLogger.__init__.
		self._log = _logger

	def process_all_pdfs(self) -> list[dict[str, str]]:
		"""Procesa todos los PDFs en la carpeta y retorna chunks de texto."""
		documents = []

		if not self.pdf_folder.exists():
			self._log.warning("Carpeta %s no existe", self.config.pdf_folder)
			return documents

		pdf_files = list(self.pdf_folder.glob("*.pdf"))
		if not pdf_files:
			self._log.warning("No se encontraron PDFs en %s", self.config.pdf_folder)
			return documents

		self._log.info("Procesando %d PDF(s)...", len(pdf_files))

		for pdf_path in pdf_files:
			try:
				chunks = self._extract_chunks_from_pdf(pdf_path)
				documents.extend(chunks)
				self._log.debug("  %s -> %d chunks", pdf_path.name, len(chunks))
			except Exception as e:
				self._log.error("Error procesando %s: %s", pdf_path.name, e)

		return documents
	
	# Matches common chapter/section heading patterns, e.g.:
	#   "Chapter 3: Clean Code"  "3. Functions"  "CHAPTER 3 – Functions"
	_HEADING_RE = re.compile(
		r'^(?:chapter\s+\d+\s*[-–:]\s*|chapter\s+\d+\s+|\d+\.\s+)(.+)',
		re.IGNORECASE,
	)

	def _extract_chapter(self, text: str) -> str:
		"""Return the first heading found in text, or empty string."""
		for line in text.splitlines():
			line = line.strip()
			m = self._HEADING_RE.match(line)
			if m:
				return line  # return the full heading line as-is
		return ""

	def _extract_chunks_from_pdf(self, pdf_path: Path) -> list[dict[str, str]]:
		"""Extrae chunks de un PDF etiquetando cada uno con su capítulo."""
		reader = PdfReader(pdf_path)

		full_text = "".join(page.extract_text() or "" for page in reader.pages)

		chunks = []
		chunk_size = self.config.chunk_size
		overlap = self.config.chunk_overlap
		current_chapter = ""

		for i in range(0, len(full_text), chunk_size - overlap):
			chunk = full_text[i:i + chunk_size]
			if not chunk.strip():
				continue
			# Update the running chapter whenever a heading appears in the chunk.
			detected = self._extract_chapter(chunk)
			if detected:
				current_chapter = detected
			chunk_id = f"{pdf_path.name}_chunk_{i}"
			chunks.append({
				"id": chunk_id,
				"text": chunk,
				"source": pdf_path.stem,
				"chapter": current_chapter,
			})

		return chunks