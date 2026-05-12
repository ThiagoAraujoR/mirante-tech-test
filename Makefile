.PHONY: help up up-core down logs build test lint typecheck eval run-annexes shell-db shell-sandbox clean validate-e2e

help:
	@echo "Targets disponíveis:"
	@echo "  up            - sobe stack completa (app + sandbox + langfuse + modernizer-api)"
	@echo "  up-core       - sobe apenas app + sandbox + modernizer-api (sem Langfuse)"
	@echo "  down          - derruba stack"
	@echo "  logs          - tail dos logs"
	@echo "  build         - rebuild da imagem modernizer-api"
	@echo "  test          - pytest"
	@echo "  lint          - ruff check"
	@echo "  typecheck     - mypy"
	@echo "  eval          - roda avaliação sobre Anexos B–F"
	@echo "  run-annexes   - executa pipeline em cada Anexo e persiste em results/"
	@echo "  shell-db      - abre psql no postgres-app"
	@echo "  shell-sandbox - abre psql no postgres-sandbox"
	@echo "  validate-e2e  - validação ponta-a-ponta (up + health + qa + smoke + annexes + eval)"
	@echo "  clean         - remove caches"

up:
	docker compose --profile observability up -d --build

up-core:
	docker compose up -d --build postgres-app postgres-sandbox modernizer-api

down:
	docker compose --profile observability down

logs:
	docker compose logs -f modernizer-api

build:
	docker compose build modernizer-api

test:
	docker compose exec -T modernizer-api pytest

lint:
	docker compose exec -T modernizer-api ruff check src tests eval

typecheck:
	docker compose exec -T modernizer-api mypy src

eval:
	docker compose exec -e MODERNIZER_API=http://localhost:2024 -T modernizer-api python -m eval.run_eval

run-annexes:
	docker compose exec -e MODERNIZER_API=http://localhost:2024 -T modernizer-api python scripts/run_annexes.py

shell-db:
	docker compose exec postgres-app psql -U mirante -d mirante

shell-sandbox:
	docker compose exec postgres-sandbox psql -U sandbox -d sandbox

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

validate-e2e:
	bash scripts/validate_e2e.sh
