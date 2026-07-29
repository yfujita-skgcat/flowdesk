# Flowdesk Makefile
#
# Usage:
#   make test       - Run all tests
#   make lint       - Run ruff linter
#   make type-check - Run mypy type checker
#   make check      - Run lint + type-check
#   make fmt        - Run ruff formatter
#   make all        - Run fmt + check + test
#   make package    - Build native PyInstaller onedir artifacts
#   make package-smoke - Smoke-test existing package artifacts
#   make package-check - Build and smoke-test package artifacts
#   make package-manifest - Write package provenance JSON
#   make upversion  - Increment the patch version
#   make pushtag    - Tag and push the current application version
#   make clean      - Remove build artifacts and caches
#   make help       - Show this help

PYTHON ?= python3
GIT ?= $(shell command -v git 2>/dev/null)
PACKAGE_SMOKE_DIR ?= artifacts/package-smoke
QT_PLATFORM ?=
PACKAGE_VERSION := $(shell $(PYTHON) tools/version.py --read)
PACKAGE_TAG := v$(PACKAGE_VERSION)

.PHONY: test test-core test-gui test-all gui-debug benchmark benchmark-density lint type-check check fmt all zip \
	package package-smoke package-check package-manifest upversion pushtag clean help

gui:
	flowdesk-gui

benchmark:
	python tools/benchmark_vector_scatter.py

benchmark-density:
	python tools/benchmark_density_plot.py

zip:
	rm -f rep.zip
	@test -n "$(GIT)" || (echo "Git executable not found" >&2; exit 1)
	$(GIT) archive --format=zip --output=rep.zip HEAD

# Legacy working-tree archive command. Kept for reference; use git archive above
# so the source archive matches the committed content uploaded by git push.
#	if [ -e rep.zip ]; then rm rep.zip; fi
#	zip -r rep.zip *.md Makefile packaging/ .github/ docs/ examples/ logs/ pyproject.toml schemas/ src/ tests/ tools/

help:
	@echo "Flowdesk Makefile targets:"
	@echo "  test        - Run all tests (pytest)"
	@echo "  test-core   - Run non-GUI tests in a separate process"
	@echo "  test-gui    - Run strict GUI tests with artifacts"
	@echo "  test-all    - Run core and GUI tests in separate processes"
	@echo "  gui-debug   - Launch GUI with diagnostic logging"
	@echo "  benchmark-density - Measure density numeric and Qt rendering costs"
	@echo "  zip         - Create a source archive from the current Git commit"
	@echo "  lint        - Run ruff linter (src/ tests/)"
	@echo "  type-check  - Run mypy type checker"
	@echo "  check       - Run lint + type-check"
	@echo "  fmt         - Run ruff formatter (src/ tests/)"
	@echo "  all         - Run fmt + check + test"
	@echo "  package     - Build native PyInstaller onedir artifacts"
	@echo "  package-smoke - Smoke-test existing package artifacts"
	@echo "  package-check - Build and smoke-test package artifacts"
	@echo "  package-manifest - Write package provenance JSON"
	@echo "  upversion  - Increment patch version ($(PACKAGE_VERSION))"
	@echo "  pushtag     - Tag and push application version ($(PACKAGE_TAG))"
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

release:
	./tools/create-release.sh

all: fmt check test

package:
	$(PYTHON) tools/package.py build

package-smoke:
	$(PYTHON) tools/package.py smoke \
		$(if $(QT_PLATFORM),--qt-platform $(QT_PLATFORM),) \
		--output-dir $(PACKAGE_SMOKE_DIR)

package-check: package
	$(MAKE) package-smoke PYTHON="$(PYTHON)" QT_PLATFORM="$(QT_PLATFORM)"

package-manifest:
	$(PYTHON) tools/package.py manifest --output $(PACKAGE_SMOKE_DIR)/build-manifest.json

upversion:
	$(PYTHON) tools/version.py --increment-patch

# pushtag:
# 	@test -n "$(PACKAGE_VERSION)" || (echo "Could not read application version" >&2; exit 1)
# 	git tag "$(PACKAGE_TAG)"
# 	git push origin "$(PACKAGE_TAG)"

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
