# Makefile for infra_tools development tasks
.PHONY: test test-verbose help clean compile

# Default target
help:
	@echo "infra_tools development tasks:"
	@echo ""
	@echo "  make test              Run all tests"
	@echo "  make test-verbose      Run all tests with verbose output"
	@echo "  make test TEST=name    Run specific test file (e.g., TEST=test_scrub_par2)"
	@echo "  make compile           Check all Python files compile"
	@echo "  make clean             Remove Python cache files"
	@echo "  make help              Show this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make test"
	@echo "  make test-verbose"
	@echo "  make test TEST=test_scrub_par2"
	@echo "  make test TEST=service_tools/test_storage_ops"

# Run tests (all or specific if TEST variable is set)
test:
ifdef TEST
	@python3 run_tests.py $(TEST)
else
	@python3 run_tests.py
endif

# Run all tests with verbose output
test-verbose:
	@python3 run_tests.py -v

# Check all Python files compile
compile:
	@echo "Checking Python compilation..."
	@find . -name "*.py" -not -path "./.git/*" -not -path "./__pycache__/*" -not -path "*/__pycache__/*" | \
		while read file; do \
			python3 -m py_compile "$$file" 2>&1 && echo "✓ $$file" || echo "✗ $$file"; \
		done | grep "✗" || echo "All Python files compile successfully"

# Clean Python cache files
clean:
	@echo "Cleaning Python cache files..."
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@echo "Clean complete"
