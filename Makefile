# Everything runs in Docker. Configuration: .env (copy from .env.example).
COMPOSE          = docker compose
COMPOSE_BA       = docker compose -f compose.ba.yml
COMPOSE_DESIGNER = docker compose -f compose.designer.yml

.PHONY: help up up-ba up-designer down build logs ps test test-ba test-wiki test-designer test-core test-core-api e2e e2e-ui e2e-assets legacy sync-storage backup psql openpencil config

help:
	@echo "make up            # whole platform  -> http://localhost:8080"
	@echo "make up-ba         # postgres + gateway + BA"
	@echo "make up-designer   # postgres + gateway + Designer"
	@echo "make openpencil    # start the default OpenPencil instance (../../BA/open-pencil)"
	@echo "make test          # BA + Designer + platform_core tests in containers"
	@echo "make down | logs | ps | psql | config"

.env:
	@test -f .env || (echo "Missing .env: cp .env.example .env and fill it" && exit 1)

up: .env
	$(COMPOSE) up -d --build

up-ba: .env
	$(COMPOSE_BA) up -d --build

up-designer: .env
	$(COMPOSE_DESIGNER) up -d --build

down:
	$(COMPOSE) down

build: .env
	$(COMPOSE) build

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

config: .env
	$(COMPOSE) config -q && $(COMPOSE_BA) config -q && $(COMPOSE_DESIGNER) config -q && echo "compose OK"

psql:
	$(COMPOSE) exec postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'

openpencil:
	cd ../../BA/open-pencil && docker compose up -d

test: test-core test-wiki test-ba test-designer test-core-api

test-ba: .env
	$(COMPOSE) --profile test run --rm --build ba-test

test-wiki: .env
	$(COMPOSE) --profile test run --rm --build wiki-test

test-designer: .env
	$(COMPOSE) --profile test run --rm --build designer-test

test-core:
	docker run --rm -v "$(CURDIR)/packages/platform_core:/src" -w /src python:3.12-slim \
		sh -c "pip install -q -e '.[dev]' && pytest -q -p no:cacheprovider"

test-core-api: .env
	$(COMPOSE) --profile test run --rm --build core-test

legacy:
	$(COMPOSE) exec core-api python -m app.legacy

e2e:
	docker run --rm --network platform_default -v "$(CURDIR)/scripts:/s:ro" python:3.12-slim python /s/e2e_access.py http://gateway

e2e-ui:
	docker run --rm --network platform_default -v "$(CURDIR)/scripts:/s" mcr.microsoft.com/playwright/python:v1.48.0-jammy 		sh -c "pip install -q playwright==1.48.0 && python /s/e2e_ui.py http://gateway"

e2e-assets:
	sh scripts/e2e_assets.sh

sync-storage:
	$(COMPOSE) exec core-api python -m platform_core.sync_storage

# Postgres dump (files are in S3 / the platform-storage volume).
backup:
	mkdir -p backups
	$(COMPOSE) exec -T postgres sh -c 'pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB -Fc -f /tmp/platform.dump'
	$(COMPOSE) cp postgres:/tmp/platform.dump backups/platform-$$(date +%Y%m%d-%H%M%S).dump
