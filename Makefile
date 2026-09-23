# Convenience targets (Linux/macOS/Git-Bash). Windows users: see scripts/*.ps1
PYTHON ?= python
PIP    ?= $(PYTHON) -m pip

.PHONY: help install install-dev demo dry-run test lint format typecheck audit security check docker docker-demo tf-check clean

help:
	@echo "install       install runtime deps (editable)"
	@echo "install-dev   install runtime + dev deps"
	@echo "demo          run the zero-cost demo scan"
	@echo "dry-run       preview cleanup candidates"
	@echo "test          run the test suite with coverage"
	@echo "lint/format   ruff lint / format"
	@echo "typecheck     mypy --strict"
	@echo "audit         pip-audit dependency scan"
	@echo "check         lint + format-check + typecheck + test"
	@echo "docker        build image;  docker-demo runs it"
	@echo "tf-check      terraform fmt/validate (optional, needs terraform)"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

demo:
	$(PYTHON) -m cloud_cost_guardian.cli.main scan --mode demo

dry-run:
	$(PYTHON) -m cloud_cost_guardian.cli.main cleanup --dry-run

test:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy

audit:
	pip-audit --skip-editable

check: lint
	ruff format --check .
	mypy
	$(PYTHON) -m pytest -q

docker:
	docker build -t cloud-cost-guardian .

docker-demo: docker
	docker run --rm cloud-cost-guardian scan --mode demo

tf-check:
	cd terraform && terraform fmt -check -recursive && terraform init -backend=false -input=false && terraform validate

clean:
	rm -rf artifacts data .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
