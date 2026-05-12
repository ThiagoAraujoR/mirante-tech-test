"""FastAPI app montado pelo langgraph cli via `http.app` no langgraph.json.

O servidor langgraph mantém suas rotas internas (`/runs`, `/threads`, etc.) e
adiciona as nossas (`/modernize`, `/health`, `/eval/latest`).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from modernizer.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(
    title="Mirante SQL→Python Modernizer",
    version="0.1.0",
    description="Pipeline híbrido (LLM + Rules) para modernização de stored procedures PL/pgSQL.",
)
app.include_router(router)
