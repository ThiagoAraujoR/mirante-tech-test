"""Rotas customizadas montadas no servidor langgraph cli."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from modernizer import __version__
from modernizer.api.schemas import HealthResponse, ModernizeRequest, ModernizeResponse
from modernizer.config import get_settings
from modernizer.db.repository import ModernizationRepository
from modernizer.graph import graph
from modernizer.observability.langfuse_setup import get_callbacks

logger = logging.getLogger(__name__)
router = APIRouter(tags=["modernizer"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    repo = ModernizationRepository()
    db_ok = await repo.ping()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "down",
        llm=f"{settings.llm_provider}:{settings.llm_model}",
        langfuse="enabled" if settings.langfuse_enabled else "disabled",
        version=__version__,
    )


@router.post("/modernize", response_model=ModernizeResponse)
async def modernize(req: ModernizeRequest) -> ModernizeResponse:
    initial_state: dict[str, Any] = {
        "source_code": req.source_code,
        "schema_context": req.db_schema,
        "llm_provider_override": req.llm_provider,
        "llm_model_override": req.llm_model,
        "attempts": 0,
        "previous_errors": [],
        "status": "pending",
    }

    config: dict[str, Any] = {"callbacks": get_callbacks(), "tags": ["modernization"]}

    try:
        final_state = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        logger.exception("Falha ao executar grafo")
        raise HTTPException(status_code=500, detail=f"graph_error: {exc}") from exc

    return ModernizeResponse(
        run_id=final_state.get("run_id"),
        status=final_state.get("status", "failure"),
        generated_code=final_state.get("generated_code"),
        report=final_state.get("report", {}),
        error_message=final_state.get("error_message"),
    )


@router.get("/eval/latest")
async def eval_latest() -> list[dict[str, Any]]:
    """Endpoint do bônus 3: últimos agregados de evaluation."""
    repo = ModernizationRepository()
    try:
        return await repo.latest_evaluation_summary()
    except Exception as exc:
        logger.exception("eval/latest falhou")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
