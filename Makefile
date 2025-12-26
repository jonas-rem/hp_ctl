# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

.PHONY: test check fix coverage install clean

test:
	pytest

check:
	ruff check src/hp_ctl tests
	mypy -p hp_ctl

fix:
	ruff check --fix src/hp_ctl tests

coverage:
	pytest --cov=src/hp_ctl --cov-report=html --cov-report=term-missing --html=htmlcov/test_report.html --self-contained-html

install:
	pip install -e ".[dev]"

clean:
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
