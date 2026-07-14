# Simple testing framework for homelab services
# This provides basic targets for running tests

.PHONY: test test-unit test-integration test-all help

# Default target
help:
	@echo "Homelab Service Testing Framework"
	@echo ""
	@echo "Usage:"
	@echo "  make test           # Run all tests"
	@echo "  make test-unit      # Run unit tests only"
	@echo "  make test-integration # Run integration tests only"
	@echo "  make test-all       # Run unit and integration tests"
	@echo ""
	@echo "Variables (can be overridden):"
	@echo "  TEST_PATH=          # Path to test files (default: ./tests)"
	@echo "  TEST_PATTERN=       # File pattern to match (default: test_*.py)"
	@echo ""
	@echo "Example:"
	@echo "  make test-unit TEST_PATH=./unit_tests"
	@echo "  make test-integration TEST_PATTERN='*_test.js'"

# Default test path and pattern
TEST_PATH ?= ./tests
TEST_PATTERN ?= test_*.py

# Find test files
TEST_FILES := $(shell find $(TEST_PATH) -name "$(TEST_PATTERN)" -type f)

test-unit:
	@echo "Running unit tests..."
	@if [ -z "$(TEST_FILES)" ]; then \
		echo "No test files found matching '$(TEST_PATTERN)' in $(TEST_PATH)"; \
		echo "Create some test files or adjust TEST_PATH/TEST_PATTERN"; \
	else \
		for test_file in $(TEST_FILES); do \
			echo "Running $$test_file..."; \
			# Determine how to run based on file extension \
			case $$test_file in \
				*.py) python3 $$test_file ;; \
				*.js) node $$test_file ;; \
				*.sh) bash $$test_file ;; \
				*) echo "Unknown test type: $$test_file"; exit 1 ;; \
			esac; \
		done; \
	fi

test-integration:
	@echo "Running integration tests..."
	@echo "Integration tests typically require running services"
	@echo "Example implementation:"
	@echo "  # Start test environment"
	@echo "  docker compose -f docker-compose.test.yml up -d"
	@echo "  # Wait for services to be ready"
	@echo "  # Run tests against test environment"
	@echo "  # Tear down"
	@echo "  docker compose -f docker-compose.test.yml down"
	@echo ""
	@echo "To implement integration tests:"
	@echo "1. Create a docker-compose.test.yml in your service directory"
	@echo "2. Write tests that start services and test against them"
	@echo "3. Use this target to run them"

test-all: test-unit test-integration
	@echo "All tests completed!"

# Helper target to create a basic test structure
init-test:
	@echo "Creating basic test structure..."
	@mkdir -p tests
	@mkdir -p tests/unit
	@mkdir -p tests/integration
	@cat > tests/unit/test_example.py << 'EOF'
#!/usr/bin/env python3
"""Example unit test"""

def test_example():
    """A simple example test"""
    assert True
    print("✓ Example unit test passed")

if __name__ == "__main__":
    test_example()
EOF
	@chmod +x tests/unit/test_example.py
	@cat > tests/integration/test_example.sh << 'EOF'
#!/usr/bin/env bash
"""Example integration test"""

echo "Running example integration test..."
echo "This would typically start services and test against them"
echo "✓ Example integration test passed"
EOF
	@chmod +x tests/integration/test_example.sh
	@echo "Created test structure in tests/unit/ and tests/integration/"
	@echo "Edit the test files to implement your actual tests"