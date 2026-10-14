.PHONY: be-dev be-test fe-install fe-dev fe-build dev docker-up docker-test docker-down docker-reset coder-up coder-host-up localhost-up demo demo-all demo-pdfs help

# ── Help ──────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── Backend ───────────────────────────────────────────────────
be-dev: ## Run FastAPI dev server (port 8000)
	.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000 --reload

be-test: ## Run pytest
	.venv/bin/pytest tests/ -v

# ── Frontend ──────────────────────────────────────────────────
fe-install: ## Install frontend dependencies
	cd frontend && npm install

fe-dev: ## Run Vite dev server (port 5173)
	cd frontend && npm run dev

fe-build: ## Build frontend for production
	cd frontend && npm run build

# ── Combined ──────────────────────────────────────────────────
dev: ## Run BE + FE concurrently
	@echo "Starting BE (port 8000) + FE (port 5173)..."
	@trap 'kill 0' EXIT; \
		$(MAKE) be-dev & \
		$(MAKE) fe-dev & \
		wait


# ── Local host (no Docker) ────────────────────────────────────
localhost-up: ## Host uvicorn:8000 + arm64 Vite:5173 (July4 DBs under /tmp if present)
	bash scripts/localhost-up.sh

# ── Demo packs (folder-driven closed cycle) ───────────────────
DEMO ?= proj_july4
DEMO_BASE_URL ?= http://127.0.0.1:8000
DEMO_UI_BASE ?= http://127.0.0.1:5173

demo-pdfs: ## Build demo wiki PDFs from wiki/**/src/*.md
	PYTHONPATH=. .venv/bin/python -m demo._runner.md_to_pdf demo

demo: demo-pdfs ## Run one demo pack (DEMO=proj_july4)
	PYTHONPATH=. .venv/bin/python -m demo._runner.run_demo demo/$(DEMO) --base-url $(DEMO_BASE_URL) --ui-base $(DEMO_UI_BASE)

demo-all: demo-pdfs ## Run all demo/proj_* packs (stop on first failure)
	PYTHONPATH=. .venv/bin/python -m demo._runner.run_demo --all --base-url $(DEMO_BASE_URL) --ui-base $(DEMO_UI_BASE)

# ── Docker ────────────────────────────────────────────────────
docker-up: ## Build and run API + Postgres + frontend (keep volumes)
	docker compose up -d --build

docker-test: ## Run pytest inside Docker
	docker compose --profile test run --rm --build test

docker-down: ## Stop containers (keep Postgres + wiki volumes)
	docker compose down

docker-reset: ## Stop containers and wipe Postgres + wiki volumes
	docker compose down -v

coder-up: ## Deploy production stack on Coder workspace (from local machine)
	tar czf - --exclude='.git' --exclude='.pytest_cache' --exclude='frontend/node_modules' --exclude='tools/bpmn_elk/node_modules' --exclude='__pycache__' --exclude='.venv' --exclude='.env' --exclude='.run' . | \
		ssh main.aquamarine-leopon-37.vupham.coder 'mkdir -p ~/apps/ba-factory && tar xzf - -C ~/apps/ba-factory'
	ssh main.aquamarine-leopon-37.vupham.coder 'cd ~/apps/ba-factory && bash deploy/coder-up.sh'

coder-host-up: ## Sync BA + latest wiki MVP, then restart host uvicorn:8010 + vite:5173
	tar czf - --exclude='.git' --exclude='.pytest_cache' --exclude='frontend/node_modules' --exclude='tools/bpmn_elk/node_modules' --exclude='__pycache__' --exclude='.venv' --exclude='.env' --exclude='.run' --exclude='**/._*' --exclude='._*' . | \
		ssh main.aquamarine-leopon-37.vupham.coder 'mkdir -p ~/apps/ba-factory && tar xzf - -C ~/apps/ba-factory'
	tar czf - --exclude='.git' --exclude='.venv' --exclude='.pytest_cache' --exclude='__pycache__' --exclude='wiki_knowledge_mvp.egg-info' --exclude='data/wiki.db' --exclude='data/wiki.db-journal' --exclude='data/blobs' --exclude='data/audit.jsonl' --exclude='**/._*' --exclude='._*' -C ../../mvp . | \
		ssh main.aquamarine-leopon-37.vupham.coder 'mkdir -p ~/apps/wiki-mvp && tar xzf - -C ~/apps/wiki-mvp'
	ssh main.aquamarine-leopon-37.vupham.coder 'chmod +x ~/apps/ba-factory/deploy/host-up.sh && cd ~/apps/ba-factory && bash deploy/host-up.sh'
