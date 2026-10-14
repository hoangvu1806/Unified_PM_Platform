# Everything runs in Docker. Configuration: .env (copy from .env.example).
COMPOSE          = docker compose
COMPOSE_BA       = docker compose -f compose.ba.yml
COMPOSE_DESIGNER = docker compose -f compose.designer.yml

.PHONY: help up up-ba up-designer down build logs ps test test-ba test-wiki test-designer test-core psql openpencil config

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

test: test-core test-wiki test-ba test-designer

test-ba: .env
	$(COMPOSE) --profile test run --rm --build ba-test

test-wiki: .env
	$(COMPOSE) --profile test run --rm --build wiki-test

test-designer: .env
	$(COMPOSE) --profile test run --rm --build designer-test

test-core:
	docker run --rm -v "$(CURDIR)/packages/platform_core:/src" -w /src python:3.12-slim \
		sh -c "pip install -q -e '.[dev]' && pytest -q -p no:cacheprovider"
