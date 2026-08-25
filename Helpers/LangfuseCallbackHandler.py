"""
Langfuse callback helper.

Provides a single ``get_callback()`` factory that returns a
``langfuse.langchain.CallbackHandler`` configured from the environment,
or ``None`` when the Langfuse keys are not set (so callers can treat it
as an optional extra callback without special-casing).

Supports langfuse v4: credentials come from the environment variables
LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST (or
LANGFUSE_BASE_URL as an alias used in this project's .env).

In v4, the CallbackHandler resolves its backing client through a
singleton registry keyed by public_key.  A Langfuse() instance must be
registered first; get_callback() handles this automatically.

Usage
-----
from Helpers.LangfuseCallbackHandler import get_callback

cb = get_callback()
callbacks = [cb] if cb else []

# Pass to a ChatOpenAI model
model = ChatOpenAI(..., callbacks=callbacks)

# Pass to agent.invoke / agent.stream
result = agent.invoke({"messages": [...]}, config={"callbacks": callbacks})
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")


def _to_trace_id(value: str) -> str:
    """Convert an arbitrary string into a valid 32-char lowercase hex trace ID.

    Langfuse v4 requires trace_id to be a 32-char lowercase hex string
    (i.e. a UUID without dashes).  We derive one deterministically from the
    input so the same session always maps to the same trace ID.
    """
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


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
        Reserved for future use; not yet supported by the v4 handler.
    trace_name:
        Human-readable label for the root trace (e.g. "CleanCodeReviewer").
        Stored as a tag on the TraceContext metadata.
    """
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    # Support both LANGFUSE_HOST (v4 canonical) and LANGFUSE_BASE_URL (this project)
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")

    if not (secret_key and public_key and host):
        return None

    try:
        from langfuse import Langfuse                   # type: ignore
        from langfuse.langchain import CallbackHandler  # type: ignore
        from langfuse.types import TraceContext         # type: ignore

        # Langfuse v4 uses a singleton registry keyed by public_key.
        # The CallbackHandler looks up that registry via get_client(); if no
        # Langfuse() instance has been registered yet it returns a disabled
        # client and emits "No Langfuse client with public key … has been
        # initialized. Skipping tracing for decorated function."
        # Explicitly constructing Langfuse() registers the client so that
        # subsequent CallbackHandler calls resolve it correctly.
        Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )

        # TraceContext only accepts trace_id (32-char hex) + optional parent_span_id.
        # Derive a stable hex trace_id from session_id when provided.
        trace_context: Optional[TraceContext] = None
        if session_id is not None:
            trace_context = TraceContext(trace_id=_to_trace_id(session_id))

        # In v4 the trace name is not a constructor argument — it is read from
        # metadata["langfuse_trace_name"] on the first root chain call.  When a
        # trace_name is requested we return a thin subclass that injects that key
        # automatically so callers don't need to touch their invoke() configs.
        if trace_name is not None:
            _name = trace_name  # capture for closure

            class _NamedCallbackHandler(CallbackHandler):  # type: ignore[misc]
                def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kwargs):  # type: ignore[override]
                    if parent_run_id is None:
                        metadata = dict(metadata or {})
                        metadata.setdefault("langfuse_trace_name", _name)
                    return super().on_chain_start(
                        serialized, inputs,
                        run_id=run_id,
                        parent_run_id=parent_run_id,
                        metadata=metadata,
                        **kwargs,
                    )

            return _NamedCallbackHandler(
                public_key=public_key,
                trace_context=trace_context,
            )

        return CallbackHandler(
            public_key=public_key,
            trace_context=trace_context,
        )
    except Exception:  # noqa: BLE001 — Langfuse unavailable or misconfigured
        return None
