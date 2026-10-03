# House interface shared by the five repositories: make test, make lint, later
# make run and make prove. Kept minimal until the extraction path is proven.

PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff

.PHONY: venv test lint index eval record

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

# The gates, over recordings and the frozen cases: no network to any model, no key.
eval: venv
	$(VENV)/bin/python -m eclusa.eval retrieval
	$(VENV)/bin/python -m eclusa.eval generation

# The only live call in the project. Needs ECLUSA_LIVE=1 and OPENAI_API_KEY in the
# environment, `pip install -e ".[live]"`, and a spending cap on the provider account.
# ARGS lets you spend one call before the other fourteen: make record ARGS="--only answer-10"
record: venv
	$(VENV)/bin/python -m eclusa.eval record --ceiling-usd 0.02 --max-total-usd 0.50 $(ARGS)
