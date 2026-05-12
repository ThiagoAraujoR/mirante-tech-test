#!/usr/bin/env bash
# =============================================================================
# Validação ponta-a-ponta do pipeline Mirante.
#
# Executa, em ordem, todos os comandos relevantes do projeto:
#   1. Pré-requisitos     — docker, docker compose, .env, chaves de LLM
#   2. Inicialização      — make up (stack completa, profile observability)
#   3. Health             — /health do modernizer-api e UI do Langfuse
#   4. QA                 — ruff, mypy, pytest dentro do container
#   5. Smoke /modernize   — POST do anexo B (caso simples)
#   6. Bateria de anexos  — scripts/run_annexes.py (materializa results/)
#   7. Evaluation         — eval/run_eval.py (métricas + persistência)
#   8. Persistência       — SELECT em modernization_history
#   9. Sumário            — quantos passaram, quantos falharam
#
# O script NÃO derruba a stack ao final — para isso, rode `make down`.
# Cada etapa é independente: uma falha não aborta as seguintes; ao final, o
# exit code é não-zero se qualquer etapa tiver falhado.
# =============================================================================

set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="${ROOT_DIR}/.e2e-logs"
mkdir -p "$LOG_DIR"
RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
SUMMARY_FILE="${LOG_DIR}/summary_${RUN_TS}.txt"

# ---------- estilo ----------
if [[ -t 1 ]]; then
    C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'
    C_BLUE='\033[0;34m'; C_BOLD='\033[1m'; C_OFF='\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''; C_OFF=''
fi

declare -a STEPS_OK=()
declare -a STEPS_FAIL=()
declare -a STEPS_SKIP=()

log()   { printf "%b[%s] %s%b\n" "$C_BLUE" "$(date -u +%H:%M:%S)" "$*" "$C_OFF"; }
ok()    { printf "%b  ✓ %s%b\n" "$C_GREEN" "$*" "$C_OFF"; }
warn()  { printf "%b  ! %s%b\n" "$C_YELLOW" "$*" "$C_OFF"; }
fail()  { printf "%b  ✗ %s%b\n" "$C_RED" "$*" "$C_OFF"; }
section() {
    printf "\n%b%s%b\n" "$C_BOLD" "──── $* ────" "$C_OFF"
}

run_step() {
    # run_step <id> <descrição> <comando...>
    local id="$1"; shift
    local desc="$1"; shift
    local log_file="${LOG_DIR}/${RUN_TS}_${id}.log"
    log "[$id] $desc"
    if "$@" >"$log_file" 2>&1; then
        ok "OK  ($id) — log: $log_file"
        STEPS_OK+=("$id")
        return 0
    else
        local rc=$?
        fail "FAIL ($id, exit=$rc) — log: $log_file"
        printf "%b%s%b\n" "$C_YELLOW" "    últimas 10 linhas:" "$C_OFF"
        tail -n 10 "$log_file" | sed 's/^/      /'
        STEPS_FAIL+=("$id")
        return $rc
    fi
}

skip_step() {
    local id="$1"; shift
    local reason="$*"
    warn "SKIP ($id) — $reason"
    STEPS_SKIP+=("$id: $reason")
}

wait_for_api() {
    # wait_for_api <max_seconds>
    local max="${1:-60}"
    local elapsed=0
    while (( elapsed < max )); do
        if curl -fsS -o /dev/null --max-time 3 http://localhost:2024/health; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

api_tool_exists() {
    # api_tool_exists <binary>
    docker compose exec -T modernizer-api which "$1" >/dev/null 2>&1
}

# ---------- 1. Pré-requisitos ----------
section "1. Pré-requisitos"

if command -v docker >/dev/null 2>&1; then
    ok "docker encontrado: $(docker --version | head -1)"
else
    fail "docker não está no PATH — abortando"
    exit 127
fi

if docker compose version >/dev/null 2>&1; then
    ok "docker compose disponível: $(docker compose version --short)"
else
    fail "docker compose v2 não encontrado — abortando"
    exit 127
fi

if [[ -f .env ]]; then
    ok ".env encontrado"
else
    if [[ -f .env.example ]]; then
        warn ".env ausente — copiando de .env.example (lembre-se de preencher chaves)"
        cp .env.example .env
    else
        fail ".env e .env.example ausentes — abortando"
        exit 1
    fi
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

LLM_KEY_OK=false
case "${LLM_PROVIDER:-anthropic}" in
    anthropic) [[ -n "${ANTHROPIC_API_KEY:-}" && "$ANTHROPIC_API_KEY" != "sk-ant-..." ]] && LLM_KEY_OK=true ;;
    openai)    [[ -n "${OPENAI_API_KEY:-}"    && "$OPENAI_API_KEY"    != "sk-..."     ]] && LLM_KEY_OK=true ;;
    gemini)    [[ -n "${GOOGLE_API_KEY:-}"    && "$GOOGLE_API_KEY"    != "..."        ]] && LLM_KEY_OK=true ;;
esac
if $LLM_KEY_OK; then
    ok "chave de API do provedor '${LLM_PROVIDER:-anthropic}' presente"
else
    warn "chave de API do provedor '${LLM_PROVIDER:-anthropic}' parece placeholder — etapas que chamam LLM vão falhar"
fi

if [[ -n "${LANGFUSE_ENCRYPTION_KEY:-}" && ${#LANGFUSE_ENCRYPTION_KEY} -eq 64 ]]; then
    ok "LANGFUSE_ENCRYPTION_KEY presente (64 chars)"
else
    warn "LANGFUSE_ENCRYPTION_KEY ausente/inválida — gerando uma"
    NEW_KEY="$(openssl rand -hex 32)"
    if grep -q '^LANGFUSE_ENCRYPTION_KEY=' .env; then
        sed -i "s|^LANGFUSE_ENCRYPTION_KEY=.*|LANGFUSE_ENCRYPTION_KEY=$NEW_KEY|" .env
    else
        printf "\nLANGFUSE_ENCRYPTION_KEY=%s\n" "$NEW_KEY" >> .env
    fi
    export LANGFUSE_ENCRYPTION_KEY="$NEW_KEY"
    ok "LANGFUSE_ENCRYPTION_KEY gerada e gravada em .env"
fi

# ---------- 2. Inicialização ----------
section "2. Inicialização (make up)"
run_step "up" "subindo stack completa (build + observability)" \
    docker compose --profile observability up -d --build || true

log "aguardando containers ficarem healthy (até 90s)..."
for i in $(seq 1 30); do
    healthy=$(docker ps --filter "name=mirante" --filter "health=healthy" -q | wc -l)
    total=$(docker ps --filter "name=mirante" -q | wc -l)
    if [[ "$healthy" -ge 5 && "$total" -ge 8 ]]; then
        ok "containers prontos: $total ativos, $healthy healthy"
        break
    fi
    sleep 3
done

# ---------- 3. Health ----------
section "3. Health checks"
log "aguardando modernizer-api responder /health (até 90s)..."
if wait_for_api 90; then
    ok "modernizer-api respondeu /health"
    STEPS_OK+=("health-api")
else
    fail "modernizer-api não respondeu em 90s"
    STEPS_FAIL+=("health-api")
fi
run_step "health-langfuse" "GET / do langfuse-web" \
    bash -c 'curl -fsS -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000/'

# ---------- 4. QA ----------
section "4. QA (lint / typecheck / test)"
run_step "lint" "ruff check src tests eval" \
    docker compose exec -T modernizer-api ruff check src tests eval || true

if api_tool_exists mypy; then
    run_step "typecheck" "mypy src" \
        docker compose exec -T modernizer-api mypy src || true
else
    skip_step "typecheck" "mypy não instalado no container (extras [dev] ausentes?)"
fi

if api_tool_exists pytest; then
    run_step "pytest" "pytest (testes unitários)" \
        docker compose exec -T modernizer-api pytest -q || true
else
    skip_step "pytest" "pytest não instalado no container (extras [dev] ausentes?)"
fi

# ---------- 5. Smoke /modernize ----------
section "5. Smoke /modernize (anexo B)"
if $LLM_KEY_OK; then
    SMOKE_LOG="${LOG_DIR}/${RUN_TS}_smoke-modernize.log"
    log "[smoke-modernize] aguardando API estável antes de POST /modernize"
    if wait_for_api 60; then
        log "[smoke-modernize] POST /modernize com annex_b_fn_saldo_cliente.sql"
        SOURCE_JSON=$(python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' \
                      examples/annex_b_fn_saldo_cliente.sql)
        if curl -fsS -X POST http://localhost:2024/modernize \
                -H 'Content-Type: application/json' \
                -d "{\"source_code\": $SOURCE_JSON}" \
                -o "$SMOKE_LOG" --max-time 300; then
            STATUS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status"))' "$SMOKE_LOG")
            ok "POST /modernize retornou status=$STATUS — payload em $SMOKE_LOG"
            STEPS_OK+=("smoke-modernize")
        else
            fail "POST /modernize falhou — payload em $SMOKE_LOG"
            STEPS_FAIL+=("smoke-modernize")
        fi
    else
        fail "API não respondeu a tempo — pulando POST"
        STEPS_FAIL+=("smoke-modernize")
    fi
else
    skip_step "smoke-modernize" "chave de LLM ausente"
fi

# ---------- 6. Bateria de anexos ----------
section "6. Bateria de anexos (scripts/run_annexes.py)"
if $LLM_KEY_OK; then
    wait_for_api 60 || warn "API não respondeu — run-annexes pode falhar"
    run_step "run-annexes" "materializa results/annex_{b,c,d,e,f}" \
        docker compose exec -e MODERNIZER_API=http://localhost:2024 -T modernizer-api \
        python scripts/run_annexes.py || true
    if compgen -G "results/*/generated.py" >/dev/null; then
        count=$(find results -mindepth 2 -maxdepth 2 -name generated.py | wc -l)
        ok "results/ contém $count generated.py"
    else
        warn "results/ não tem generated.py (verifique o log de run-annexes)"
    fi
else
    skip_step "run-annexes" "chave de LLM ausente"
fi

# ---------- 7. Evaluation ----------
section "7. Evaluation (eval/run_eval.py)"
if $LLM_KEY_OK; then
    wait_for_api 60 || warn "API não respondeu — eval pode falhar"
    run_step "eval" "métricas ast_parse / structural / exec_eq / llm_judge" \
        docker compose exec -e MODERNIZER_API=http://localhost:2024 -T modernizer-api \
        python -m eval.run_eval || true
    run_step "eval-latest" "GET /eval/latest" \
        bash -c 'curl -fsS http://localhost:2024/eval/latest | head -c 2000'
else
    skip_step "eval" "chave de LLM ausente"
    skip_step "eval-latest" "chave de LLM ausente"
fi

# ---------- 8. Persistência ----------
section "8. Persistência (SELECT em modernization_history)"
run_step "persistencia" "últimos 5 registros" \
    docker compose exec -T postgres-app psql -U "${APP_POSTGRES_USER:-mirante}" -d "${APP_POSTGRES_DB:-mirante}" \
    -c "SELECT id, status, llm_provider, llm_model, latency_ms FROM modernization_history ORDER BY created_at DESC LIMIT 5;" \
    || true

# ---------- 9. Sumário ----------
section "9. Sumário"
{
    echo "Execução: $RUN_TS"
    echo "OK     (${#STEPS_OK[@]}): ${STEPS_OK[*]:-nenhum}"
    echo "FAIL   (${#STEPS_FAIL[@]}): ${STEPS_FAIL[*]:-nenhum}"
    echo "SKIP   (${#STEPS_SKIP[@]}):"
    for s in "${STEPS_SKIP[@]:-}"; do
        [[ -n "$s" ]] && echo "  - $s"
    done
    echo
    echo "Endpoints:"
    echo "  - modernizer-api: http://localhost:2024 (/health, /modernize, /eval/latest)"
    echo "  - langfuse-web  : http://localhost:3000"
    echo
    echo "Logs detalhados: $LOG_DIR"
    echo "Para derrubar a stack: make down"
} | tee "$SUMMARY_FILE"

if [[ ${#STEPS_FAIL[@]} -gt 0 ]]; then
    printf "\n%b%s%b\n" "$C_RED" "Validação concluiu com falhas." "$C_OFF"
    exit 1
fi

printf "\n%b%s%b\n" "$C_GREEN" "Validação concluiu sem falhas." "$C_OFF"
exit 0
