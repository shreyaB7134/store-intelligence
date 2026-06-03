#!/bin/bash
# Run the full test suite
# Usage: ./scripts/run_tests.sh

set -e

echo "Installing test dependencies..."
pip install -q -r requirements.test.txt

echo "Running tests..."
pytest tests/ \
    -v \
    --tb=short \
    --cov=app \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    "$@"

echo ""
echo "Test run complete. Coverage report: htmlcov/index.html"
