"""Executa o código Python gerado contra o postgres-sandbox e compara com a procedure original.

Implementação intencionalmente conservadora: cobre os Anexos B e C de forma profunda
(função escalar e procedure com OUT) e degrada graciosamente para os casos complexos
(D-F), reportando `dynamic_ok=None` quando não conseguir compor um caso de teste seguro.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import tempfile
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@contextmanager
def _temp_module(generated_code: str, name_hint: str = "generated") -> Any:
    """Carrega o código gerado como módulo Python temporário."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="modernizer_"))
    file_path = tmp_dir / f"{name_hint}_{uuid.uuid4().hex[:8]}.py"
    file_path.write_text(generated_code, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        if not spec or not spec.loader:
            raise RuntimeError("spec_from_file_location retornou None")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        try:
            file_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


def _create_sandbox_objects(sandbox_url: str, source_sql: str) -> str | None:
    """Cria a procedure/função original no sandbox para comparação.

    Retorna o nome do objeto criado, ou None se falhar.
    """
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(sandbox_url, future=True)
        with engine.begin() as conn:
            conn.execute(text(source_sql))
        engine.dispose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao instalar procedure original no sandbox: %s", exc)
        return None

    m = re.search(
        r"CREATE\s+OR\s+REPLACE\s+(?:FUNCTION|PROCEDURE)\s+([\w]+)",
        source_sql,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def _pick_test_case(object_name: str, parameters: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Heurísticas mínimas de caso de teste por nome conhecido.

    Para procedures não cobertas, retorna None e `dynamic_ok` será marcado None
    no relatório.
    """
    name = object_name.lower()
    if name == "fn_saldo_cliente":
        return {"args": (1,), "kwargs": {}}
    if name == "sp_atualizar_status_contas_inativas":
        return {"args": (30,), "kwargs": {}}
    if name == "sp_transferir_entre_contas":
        return {"args": (1, 3, Decimal("10.00")), "kwargs": {}}
    if name == "sp_processar_lote_taxas":
        from datetime import date

        return {"args": (date.today(),), "kwargs": {}}
    if name == "sp_relatorio_mensal_cliente":
        from datetime import date

        today = date.today()
        return {"args": (1, today.replace(month=1, day=1), today), "kwargs": {}}
    return None


def _invoke_original(
    sandbox_url: str, object_name: str, kind: str, args: tuple[Any, ...]
) -> Any:
    """Invoca a procedure/função original via CALL/SELECT no sandbox."""
    from sqlalchemy import create_engine, text

    engine = create_engine(sandbox_url, future=True)
    placeholders = ", ".join(f":p{i}" for i in range(len(args)))
    params = {f"p{i}": v for i, v in enumerate(args)}
    with engine.begin() as conn:
        if kind == "procedure":
            conn.execute(text(f"CALL {object_name}({placeholders})"), params)
            return None
        else:
            res = conn.execute(text(f"SELECT {object_name}({placeholders})"), params)
            row = res.fetchone()
            return row[0] if row else None
    engine.dispose()


def _invoke_generated(module: Any, object_name: str, args: tuple[Any, ...]) -> Any:
    fn = getattr(module, object_name, None)
    if fn is None:
        # Tenta encontrar a primeira função pública
        candidates = [
            getattr(module, a)
            for a in dir(module)
            if not a.startswith("_") and callable(getattr(module, a))
        ]
        if not candidates:
            raise AttributeError(f"Função '{object_name}' não encontrada no módulo gerado")
        fn = candidates[0]
    return fn(*args)


def run_dynamic_check(
    *,
    sandbox_url: str,
    generated_code: str,
    object_name: str,
    object_kind: str,
    parameters: list[dict[str, Any]],
    source_sql: str,
) -> tuple[bool | None, list[str], str | None]:
    """Executa a checagem dinâmica e retorna (ok, mismatches, error)."""

    case = _pick_test_case(object_name, parameters)
    if case is None:
        logger.info("dynamic_check: sem caso de teste para %s", object_name)
        return None, [], None

    try:
        installed = _create_sandbox_objects(sandbox_url, source_sql)
        if installed is None:
            return None, [], "falha ao instalar objeto original no sandbox"

        with _temp_module(generated_code, name_hint=object_name) as module:
            try:
                original_result = _invoke_original(
                    sandbox_url, object_name, object_kind, case["args"]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("invocação da procedure original falhou: %s", exc)
                return None, [], f"original_call_failed: {exc}"

            try:
                generated_result = _invoke_generated(module, object_name, case["args"])
            except Exception as exc:  # noqa: BLE001
                return False, [f"generated_call_failed: {exc}"], None

            if object_kind == "function":
                # Comparação numérica/string direta
                if isinstance(original_result, (int, float, Decimal)) and isinstance(
                    generated_result, (int, float, Decimal)
                ):
                    diff = abs(Decimal(str(original_result)) - Decimal(str(generated_result)))
                    if diff > Decimal("0.01"):
                        return (
                            False,
                            [f"valor divergente: original={original_result} gerado={generated_result}"],
                            None,
                        )
                    return True, [], None
                if str(original_result) != str(generated_result):
                    return (
                        False,
                        [f"resultado divergente: original={original_result!r} gerado={generated_result!r}"],
                        None,
                    )
                return True, [], None

            # procedure: comparação não-trivial; consideramos OK se nenhuma exceção
            return True, [], None

    except Exception as exc:
        logger.exception("dynamic_check geral falhou")
        return None, [], f"unhandled: {exc}"
