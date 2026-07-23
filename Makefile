# Flowdesk Makefile
#
# Usage:
#   make test       - Run all tests
#   make lint       - Run ruff linter
#   make type-check - Run mypy type checker
#   make check      - Run lint + type-check
#   make fmt        - Run ruff formatter
#   make all        - Run fmt + check + test
#   make package    - Build a native PyInstaller onedir artifact
#   make package-smoke - Smoke-test the native package artifact
#   make clean      - Remove build artifacts and caches
#   make help       - Show this help

FLOWDESK_PYTHON ?= .direnv/python-3.12.13/bin/python
PYINSTALLER = $(FLOWDESK_PYTHON) -m PyInstaller
PACKAGE_SPEC ?= packaging/flowdesk.spec
PACKAGE_GUI ?= dist/flowdesk/flowdesk
PACKAGE_SMOKE_DIR ?= artifacts/package-smoke

.PHONY: test test-core test-gui test-all gui-debug lint type-check check fmt all \
	package package-smoke clean help

gui:
	flowdesk-gui

zip:
	if [ -e rep.zip ]; then rm rep.zip; fi
	zip -r rep.zip *.md Makefile  packaging/ .github/ docs/ examples/ logs/ pyproject.toml  schemas/ src/ tests/ tools/

help:
	@echo "Flowdesk Makefile targets:"
	@echo "  test        - Run all tests (pytest)"
	@echo "  test-core   - Run non-GUI tests in a separate process"
	@echo "  test-gui    - Run strict GUI tests with artifacts"
	@echo "  test-all    - Run core and GUI tests in separate processes"
	@echo "  gui-debug   - Launch GUI with diagnostic logging"
	@echo "  lint        - Run ruff linter (src/ tests/)"
	@echo "  type-check  - Run mypy type checker"
	@echo "  check       - Run lint + type-check"
	@echo "  fmt         - Run ruff formatter (src/ tests/)"
	@echo "  all         - Run fmt + check + test"
	@echo "  package     - Build native PyInstaller onedir artifact"
	@echo "  package-smoke - Smoke-test the native package artifact"
	@echo "  clean       - Remove build artifacts and caches"
	@echo "  help        - Show this help"

test:
	pytest tests/ -v

test-core:
	.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -m "not gui" tests/ -v

test-gui:
	./tools/run-gui-tests.sh

test-all:
	$(MAKE) test-core
	$(MAKE) test-gui

gui-debug:
	./tools/run-gui-debug.sh

lint:
	ruff check src/ tests/

type-check:
	mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli

check: lint type-check

fmt:
	ruff format src/ tests/

all: fmt check test

package:
	$(PYINSTALLER) --clean --noconfirm $(PACKAGE_SPEC)
	echo "For windows."
	echo python tools/package.py build
	echo python tools/package.py smoke

package-smoke: package
	QT_QPA_PLATFORM=offscreen $(FLOWDESK_PYTHON) packaging/smoke_test.py \
		--gui $(PACKAGE_GUI) \
		--output-dir $(PACKAGE_SMOKE_DIR)

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf src/__pycache__
	rm -rf src/*/__pycache__
	rm -rf tests/__pycache__
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} +
