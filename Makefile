# House interface shared by the five repositories: make test, make lint, later
# make run and make prove. Kept minimal until the extraction path is proven.

PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff

.PHONY: venv test lint index eval record image kind-up deploy smoke kind-down prove

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

# ---------------------------------------------------------------------------
# The cluster. Docker and kind are the only things here that are not Python.
IMAGE ?= eclusa:dev
CLUSTER ?= eclusa

# The index is built inside the image, so this takes a few minutes the first time:
# it downloads the pinned embedding model and embeds the whole corpus.
image:
	docker build -t $(IMAGE) .

kind-up:
	kind create cluster --name $(CLUSTER) --config k8s/kind.yaml

# The image is built here and loaded into the cluster; it never comes from a registry.
deploy: image
	kind load docker-image $(IMAGE) --name $(CLUSTER)
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
	kubectl -n eclusa rollout status deployment/eclusa --timeout=300s

smoke:
	./scripts/smoke.sh

kind-down:
	kind delete cluster --name $(CLUSTER)

# Everything, from nothing to an answered question out of a pod.
prove: kind-up deploy smoke
