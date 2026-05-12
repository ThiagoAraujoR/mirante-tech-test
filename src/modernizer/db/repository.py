"""Repository com a operação de persistência das execuções."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from modernizer.db.models import EvaluationResult, ModernizationRun
from modernizer.db.session import get_session_factory

logger = logging.getLogger(__name__)


class ModernizationRepository:
    """Persiste uma execução do pipeline.

    A operação é best-effort: se o banco estiver indisponível, registra o erro
    em log mas não bloqueia o retorno da API ao usuário (a execução em si pode
    ter sido bem-sucedida).
    """

    async def save_run(
        self,
        *,
        source_code: str,
        generated_code: str | None,
        report: dict[str, Any],
        status: str,
        llm_provider: str | None,
        llm_model: str | None,
        latency_ms: int | None,
        cost_usd: Decimal | None,
        error_message: str | None,
    ) -> uuid.UUID | None:
        factory = get_session_factory()
        try:
            async with factory() as session:
                run = ModernizationRun(
                    source_code=source_code,
                    generated_code=generated_code,
                    report=report,
                    status=status,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                    error_message=error_message,
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)
                return run.id
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao persistir modernization_run: %s", exc)
            return None

    async def save_evaluation(
        self,
        *,
        run_id: uuid.UUID | None,
        annex: str,
        metric_name: str,
        metric_value: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        factory = get_session_factory()
        try:
            async with factory() as session:
                ev = EvaluationResult(
                    run_id=run_id,
                    annex=annex,
                    metric_name=metric_name,
                    metric_value=Decimal(str(metric_value)),
                    details=details,
                )
                session.add(ev)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao persistir evaluation_result: %s", exc)

    async def latest_evaluation_summary(self) -> list[dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT annex, metric_name, AVG(metric_value) AS avg_value,
                           COUNT(*) AS n
                    FROM evaluation_results
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                    GROUP BY annex, metric_name
                    ORDER BY annex, metric_name
                    """
                )
            )
            return [dict(row._mapping) for row in result.fetchall()]

    async def ping(self) -> bool:
        factory = get_session_factory()
        try:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
                return True
        except Exception:  # noqa: BLE001
            return False
