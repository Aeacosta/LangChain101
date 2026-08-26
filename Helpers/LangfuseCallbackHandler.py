"""
Langfuse callback helper.

Provides a single ``get_callback()`` factory that returns a
``langfuse.langchain.CallbackHandler`` configured from the environment,
or ``None`` when the Langfuse keys are not set (so callers can treat it
as an optional extra callback without special-casing).

Supports langfuse v4: credentials come from the environment variables
LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST (or
LANGFUSE_BASE_URL as an alias used in this project's .env).

In v4, trace_name is set via the ``propagate_attributes`` OTel context
manager, not through CallbackHandler constructor arguments or metadata
injection.  Use ``trace_name_context(name)`` to wrap each invocation so
that the trace carries the correct name in Langfuse.

Usage
-----
from Helpers.LangfuseCallbackHandler import get_callback, trace_name_context

cb = get_callback()
callbacks = [cb] if cb else []

with trace_name_context("MyAgent"):
    result = agent.invoke({"messages": [...]}, config={"callbacks": callbacks})
"""

from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")


def _to_trace_id(value: str) -> str:
    """Convert an arbitrary string into a valid 32-char lowercase hex trace ID."""
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


@contextmanager
def trace_name_context(name: str):
    """Sync context manager that sets the Langfuse trace name for the duration of the block.

    In Langfuse v4 the trace name is propagated via OpenTelemetry context, not via
    CallbackHandler metadata.  Wrap every agent invocation with this so that the
    trace appears under the correct name in the Langfuse UI.

    Example
    -------
    with trace_name_context("CleanCodeReviewer"):
        result = agent.invoke(..., config={"callbacks": callbacks})
    """
    try:
        from langfuse import propagate_attributes  # type: ignore
        with propagate_attributes(trace_name=name):
            yield
    except Exception:
        # Langfuse unavailable or not configured — just run the block normally.
        yield


@asynccontextmanager
async def async_trace_name_context(name: str):
    """Async context manager that sets the Langfuse trace name for async invocations.

    Example
    -------
    async with async_trace_name_context("XTPPRDiscoveryAgent"):
        result = await agent.ainvoke(...)
    """
    try:
        from langfuse import propagate_attributes  # type: ignore
        with propagate_attributes(trace_name=name):
            yield
    except Exception:
        yield


def get_callback(
    session_id: str | None = None,
    user_id: str | None = None,
    trace_name: str | None = None,
) -> Optional[object]:
    """Return a configured ``langfuse.langchain.CallbackHandler`` or ``None``.

    The handler is only instantiated when *all three* Langfuse environment
    variables are present:

        LANGFUSE_SECRET_KEY
        LANGFUSE_PUBLIC_KEY
        LANGFUSE_HOST  (or LANGFUSE_BASE_URL as alias)

    Parameters
    ----------
    session_id:
        Logical session identifier (e.g. a file path or SHA pair).  Hashed
        into a valid 32-char hex trace ID so the same session always maps to
        the same Langfuse trace.
    user_id:
        Reserved for future use.
    trace_name:
        Kept for backwards-compatibility but no longer used to set the trace
        name on the handler.  Use ``trace_name_context(name)`` instead to wrap
        the invocation call.
    """
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")

    if not (secret_key and public_key and host):
        return None

    try:
        from langfuse import Langfuse                   # type: ignore
        from langfuse.langchain import CallbackHandler  # type: ignore
        from langfuse.types import TraceContext         # type: ignore

        Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )

        trace_context: Optional[TraceContext] = None
        if session_id is not None:
            trace_context = TraceContext(trace_id=_to_trace_id(session_id))

        return CallbackHandler(
            public_key=public_key,
            trace_context=trace_context,
        )
    except Exception:  # noqa: BLE001 — Langfuse unavailable or misconfigured
        return None
