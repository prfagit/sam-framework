SHELL := /bin/bash

.PHONY: test test-all lint format typecheck

test:
	SAM_TEST_MODE=1 bash scripts/test.sh

test-all:
	uv run pytest -q

lint:
	uv run ruff check --fix

format:
	uv run ruff format

typecheck:
	uv run mypy sam/

