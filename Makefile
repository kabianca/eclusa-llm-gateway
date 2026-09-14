# House interface shared by the five repositories: make test, make lint, later
# make run and make prove. Kept minimal until the extraction path is proven.

PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff

.PHONY: venv test lint index

$(VENV)/bin/activate: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e ".[dev]"
	touch $(VENV)/bin/activate

venv: $(VENV)/bin/activate

test: venv
	$(PYTEST)

lint: venv
	$(RUFF) check .
	$(RUFF) format --check .

# Segment, chunk and embed the corpus into var/index (about two minutes single-threaded;
# the image build runs the same command). The model is fetched once, pinned by revision.
index: venv
	$(VENV)/bin/python -m eclusa.index build --out var/index
