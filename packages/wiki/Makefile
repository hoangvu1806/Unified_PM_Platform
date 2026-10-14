PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin
export PYTHONPATH := .

.PHONY: all install seed seed-approve run mcp test clean reset

all: install
	@echo ""
	@echo "Next:"
	@echo "  make reset         # wipe DB/blobs (keep samples if any)"
	@echo "  make seed          # sample PDFs → DRAFT (uses WIKI_SORT / .env)"
	@echo "  make run           # UI http://127.0.0.1:8000"
	@echo "  make test"

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e ".[dev]"

install: $(VENV)/bin/python

seed: install
	$(BIN)/python -m wiki.seed

seed-approve: install
	$(BIN)/python -m wiki.seed --approve

run: install
	$(BIN)/uvicorn wiki.http_app:app --reload --host 127.0.0.1 --port 8000

mcp: install
	$(BIN)/python -m wiki.mcp_server

test: install
	$(BIN)/pytest -q

clean:
	rm -f data/wiki.db data/audit.jsonl
	rm -rf data/blobs data/samples
	mkdir -p data

reset:
	rm -f data/wiki.db data/audit.jsonl
	rm -rf data/blobs
	mkdir -p data/blobs data/samples
	@echo "DB cleared. Refresh UI or use Clear wiki DB. Samples kept if present."
