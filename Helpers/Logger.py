"""Logger dedicado al ciclo agentic.

Usa el módulo estándar `logging` con un handler de consola formateado con
colores ANSI para distinguir niveles visualmente (sin dependencias externas).

Uso típico
----------
from core.agent_logger import AgentLogger

log = AgentLogger()                          # nivel INFO, solo consola
log = AgentLogger(level="DEBUG")             # activa todos los niveles
log = AgentLogger(level="DEBUG", log_file="agent.log")  # también a archivo
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Generator


# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"

# Foreground colors
_FG_CYAN    = "\033[36m"
_FG_GREEN   = "\033[32m"
_FG_YELLOW  = "\033[33m"
_FG_RED     = "\033[31m"
_FG_MAGENTA = "\033[35m"
_FG_BLUE    = "\033[34m"
_FG_WHITE   = "\033[37m"

# Level → color mapping
_LEVEL_COLORS: dict[str, str] = {
    "DEBUG":    _DIM + _FG_CYAN,
    "INFO":     _FG_GREEN,
    "WARNING":  _FG_YELLOW,
    "ERROR":    _BOLD + _FG_RED,
    "CRITICAL": _BOLD + _FG_MAGENTA,
}

# ---------------------------------------------------------------------------
# Custom formatter
# ---------------------------------------------------------------------------

class _CallbackHandler(logging.Handler):
    """
    A logging handler that forwards every formatted record to a
    plain callable — used to pipe log output to the SSE UI sink.
    ANSI colour codes are stripped so the browser receives clean text.
    """

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

    def __init__(self, callback: "Callable[[str], None]") -> None:
        super().__init__()
        self._callback = callback
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        try:
            msg = self.format(record)
            msg = self._ANSI_RE.sub("", msg)   # strip colour codes
            self._callback(msg)
        except Exception:
            self.handleError(record)


class _FancyFormatter(logging.Formatter):
    """
    Formatter con colores ANSI y badges de nivel alineados.

    Formato:
        HH:MM:SS  [LEVEL]  message
    """

    _BADGE_WIDTH = 9   # len("[WARNING]") == 9

    def __init__(self, use_color: bool = True) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        level  = record.levelname
        color  = _LEVEL_COLORS.get(level, "") if self._use_color else ""
        reset  = _RESET if self._use_color else ""
        dim    = _DIM   if self._use_color else ""
        bold   = _BOLD  if self._use_color else ""

        badge  = f"[{level}]".ljust(self._BADGE_WIDTH)
        time_s = self.formatTime(record, self.datefmt)

        time_str  = f"{dim}{time_s}{reset}"
        badge_str = f"{color}{bold}{badge}{reset}"
        msg_str   = f"{color}{record.getMessage()}{reset}"

        return f"{time_str}  {badge_str}  {msg_str}"


# ---------------------------------------------------------------------------
# AgentLogger
# ---------------------------------------------------------------------------

# Names of all child loggers that should inherit the root handler
_CHILD_LOGGERS = (
    "agente.config",
    "agente.llm_client",
    "agente.llm_utils",
    "pdf_processor",
    "vector_store",
    "rag_agent",
)


class AgentLogger:
    """
    Logger con formato legible y colores para el ciclo agentic.

    Niveles usados
    --------------
    INFO   — inicio, iteraciones, stop_reason, respuesta final
    DEBUG  — preview de inputs/outputs de cada tool, detalles HTTP
    ERROR  — errores capturados durante la ejecución de tools
    """

    _LINE = "─" * 62

    def __init__(
        self,
        name: str = "agente",
        level: str = "INFO",
        log_file: str | None = None,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level.upper())

        # Evitar duplicar handlers si se instancia más de una vez con el mismo nombre
        if not self._logger.handlers:
            use_color = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else True

            fancy = _FancyFormatter(use_color=use_color)

            # Handler de consola (stdout)
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(fancy)
            self._logger.addHandler(console)

            # Handler de archivo (sin color, plain text)
            if log_file:
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setFormatter(_FancyFormatter(use_color=False))
                self._logger.addHandler(file_handler)

        # Evitar que el logger raíz duplique mensajes
        self._logger.propagate = False

        # Propagar el nivel y los handlers a todos los sub-loggers del proyecto.
        # - Loggers con prefijo "agente." pueden propagar hacia arriba naturalmente.
        # - Loggers sin ese prefijo (pdf_processor, vector_store, rag_agent) se
        #   registran directamente con los handlers del logger raíz.
        for child_name in _CHILD_LOGGERS:
            child = logging.getLogger(child_name)
            child.setLevel(level.upper())
            if child_name.startswith(name + "."):
                # Es descendiente directo — basta con propagar hacia arriba
                child.propagate = True
            else:
                # Logger independiente — copiar los handlers del logger raíz
                child.propagate = False
                for handler in self._logger.handlers:
                    if handler not in child.handlers:
                        child.addHandler(handler)

    # ------------------------------------------------------------------
    # Métodos de ciclo agentic
    # ------------------------------------------------------------------

    def inicio(self, question: str, tool_names: list[str]) -> None:
        self._logger.info(self._LINE)
        self._logger.info("AGENTE  |  tools: %s", tool_names)
        preview = question[:120] + ("..." if len(question) > 120 else "")
        self._logger.info("Pregunta: %s", preview)
        self._logger.info(self._LINE)

    def iteracion(self, numero: int) -> None:
        self._logger.info("[iter %d] Llamando al modelo...", numero)

    def stop_reason(self, reason: str) -> None:
        self._logger.info("stop_reason=%r", reason)

    def tool_llamada(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        input_str = json.dumps(tool_input, ensure_ascii=False)
        if len(input_str) > 120:
            input_str = input_str[:120] + "..."
        self._logger.info("→ tool_use: %s(%s)", tool_name, input_str)

    def tool_resultado(self, tool_name: str, result: str) -> None:
        preview = result[:80].replace("\n", " ")
        suffix = f" ... [{len(result)} chars]" if len(result) > 80 else ""
        self._logger.debug("← %s resultado: %s%s", tool_name, preview, suffix)

    def tool_error(self, tool_name: str, exc: Exception) -> None:
        self._logger.error("✗ Error en tool %r: %s", tool_name, exc)

    def stream_token(self, token: str) -> None:
        self._logger.debug("◂ %s", token)

    def respuesta_final(self, answer: str) -> None:
        self._logger.info(self._LINE)
        self._logger.info("Respuesta final  (%d caracteres)", len(answer))
        self._logger.info(self._LINE)

    def stop_inesperado(self, reason: str) -> None:
        self._logger.warning("stop_reason inesperado: %r — saliendo del ciclo.", reason)

    # ------------------------------------------------------------------
    # UI sink
    # ------------------------------------------------------------------

    def add_ui_sink(self, callback: Callable[[str], None]) -> None:
        """
        Attach a callback that receives every log line as plain text
        (ANSI codes stripped). Call this once after construction to
        forward all logger output — including timer messages and child
        loggers — to the SSE UI stream.

        Parameters
        ----------
        callback : callable(str)
            Function to call with each log message, e.g. ``emit``.
        """
        handler = _CallbackHandler(callback)
        handler.setLevel(self._logger.level)

        # Attach to the root logger and all child loggers.
        self._logger.addHandler(handler)
        for child_name in _CHILD_LOGGERS:
            child = logging.getLogger(child_name)
            if handler not in child.handlers:
                child.addHandler(handler)

    # ------------------------------------------------------------------
    # Timing helper
    # ------------------------------------------------------------------

    @contextmanager
    def timer(self, label: str) -> Generator[None, None, None]:
        """
        Context manager that logs the wall-clock duration of a code block.

        Usage
        -----
        with logger.timer("RAG indexing"):
            vector_store.add_documents(chunks)

        Emits two INFO lines:
            ▶ RAG indexing ...
            ✓ RAG indexing  completed in 1.23 s
        """
        self._logger.info("▶ %s ...", label)
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            self._logger.info("✓ %s  completado en %.2f s", label, elapsed)