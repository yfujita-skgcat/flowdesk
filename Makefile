# Flowdesk Makefile
#
# Usage:
#   make test       - Run all tests
#   make lint       - Run ruff linter
#   make type-check - Run mypy type checker
#   make check      - Run lint + type-check
#   make fmt        - Run ruff formatter
#   make all        - Run fmt + check + test
#   make clean      - Remove build artifacts and caches
#   make help       - Show this help

.PHONY: test lint type-check check fmt all clean help

help:
	@echo "Flowdesk Makefile targets:"
	@echo "  test        - Run all tests (pytest)"
	@echo "  lint        - Run ruff linter (src/ tests/)"
	@echo "  type-check  - Run mypy type checker"
	@echo "  check       - Run lint + type-check"
	@echo "  fmt         - Run ruff formatter (src/ tests/)"
	@echo "  all         - Run fmt + check + test"
	@echo "  clean       - Remove build artifacts and caches"
	@echo "  help        - Show this help"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

type-check:
	mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli

check: lint type-check

fmt:
	ruff format src/ tests/

all: fmt check test

clean:
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf src/__pycache__
	rm -rf src/*/__pycache__
	rm -rf tests/__pycache__
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} +
