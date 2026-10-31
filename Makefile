GATES := format

.PHONY: check check-all lock exemptions test format lint types filepawl hooks hooks-installed

check:
	$(MAKE) --keep-going check-all

check-all: lock exemptions $(GATES) test

lock:
	uv lock --check

exemptions:
	uv run python -m gates.exemptions $(GATES)

test:
	uv run pytest

format:
	uv run ruff format --check relay gates tests

lint:
	uv run ruff check relay gates tests

types:
	uv run mypy

filepawl:
	false

hooks:
	git config core.hooksPath .githooks

hooks-installed:
	test "$$(git config core.hooksPath)" = .githooks
