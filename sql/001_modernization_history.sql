-- =============================================================
-- Tabela de persistência das execuções do pipeline híbrido.
-- Toda execução é gravada aqui, inclusive falhas.
-- =============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS modernization_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code     TEXT NOT NULL,
    generated_code  TEXT,
    report          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(20) NOT NULL
                    CHECK (status IN ('success', 'failure', 'partial')),
    llm_provider    VARCHAR(50),
    llm_model       VARCHAR(100),
    latency_ms      INTEGER,
    cost_usd        NUMERIC(10, 6),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_modernization_status_date
    ON modernization_history (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_modernization_created_at
    ON modernization_history (created_at DESC);

-- Tabela auxiliar para resultados de avaliação (bônus 3).
CREATE TABLE IF NOT EXISTS evaluation_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES modernization_history(id) ON DELETE CASCADE,
    annex           VARCHAR(10) NOT NULL,
    metric_name     VARCHAR(80) NOT NULL,
    metric_value    NUMERIC(10, 4) NOT NULL,
    details         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evaluation_annex_metric
    ON evaluation_results (annex, metric_name, created_at DESC);
