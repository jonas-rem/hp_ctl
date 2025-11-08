# HP Control

A modular Python project for HP device control.

## Quick Start

### Prerequisites

- Python 3.12 or higher
- `pip` and `venv`

### Development Setup

```bash
git clone <repository-url>
cd hp-ctl
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pip install tox
```

### Production Installation

```bash
# Install from local
pip install .
# Install from Repository link
pip install -e git+https://github.com/jonas-rem/hp-ctl.git#egg=hp-ctl
```

## Testing

### With Tox

```bash
# Run all checks (tests, lint, type checking)
tox

# Run only tests
tox -e py

# Run with coverage
tox -e coverage
```

### Directly with Pytest

```bash
pytest
pytest --cov=hp_ctl --cov-report=html
```

## Code Quality

```bash
# Linting
ruff check hp_ctl tests

# Type checking
mypy hp_ctl
```

