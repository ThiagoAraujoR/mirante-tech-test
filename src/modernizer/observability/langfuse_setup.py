"""Integração com Langfuse — callback handler do LangChain/LangGraph."""

from __future__ import annotations

import logging
from typing import Any

from modernizer.config import get_settings

logger = logging.getLogger(__name__)

_callback_singleton: Any | None = None
_resolved = False


def _resolve_callback() -> Any | None:
    """Tenta diferentes imports do callback handler do Langfuse.

    O pacote langfuse passou por reorganizações entre v2 e v3; tentamos as
    posições conhecidas e degradamos para None se o pacote estiver ausente.
    """
    global _callback_singleton, _resolved
    if _resolved:
        return _callback_singleton

    settings = get_settings()
    _resolved = True

    if not settings.langfuse_enabled:
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("LANGFUSE_ENABLED=true mas chaves não configuradas; desabilitando")
        return None

    handler_cls = None
    try:  # langfuse v2 / v3
        from langfuse.callback import CallbackHandler

        handler_cls = CallbackHandler
    except ImportError:
        try:
            from langfuse.langchain import CallbackHandler

            handler_cls = CallbackHandler
        except ImportError:
            logger.warning("Langfuse callback não disponível no ambiente; segue sem observability")
            return None

    try:
        _callback_singleton = handler_cls(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse callback instanciado (host=%s)", settings.langfuse_host)
    except Exception as exc:  # noqa: BLE001
        logger.warning("falha ao instanciar Langfuse callback: %s", exc)
        _callback_singleton = None

    return _callback_singleton


def get_callbacks() -> list[Any]:
    """Retorna a lista de callbacks a passar ao graph.ainvoke."""
    handler = _resolve_callback()
    return [handler] if handler is not None else []
