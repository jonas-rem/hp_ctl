# HP Control

A project that allows you to control a Panasonic Aquarea Heatpump from a Linux
PC over UART. Panasonic Aquarea Heatpumps have a UART connection that allow to
read and write settings. The Heishamon Project uses this fact to connect a
wireless device to the UART interface and read/write to it. All data is
provided via MQTT to e.g. Home Assistant.

This project allows to directly connect a Linux Machine to the Heatpump via
UART. The system still publishes to an MQTT broker.

## Features

- Format Decoding
- Publish to MQTT broker
- Test coverage via pytest
- Mockup MQTT broker for testing

## Modules

### protocol.py
Defines all static protocol data: topic names, byte positions, conversion
functions, and lookup tables. This is the single source of truth for the
Panasonic heatpump protocol structure and is imported by both encoder and
decoder.

### decoder.py
Reads raw byte arrays from the heatpump and converts them to human-readable
values using the protocol definitions. Handles special cases like fractional
temperatures and multi-byte values.

### encoder.py
Takes human-readable values and command parameters, then converts them to raw
byte arrays ready to send to the heatpump. Mirrors the decoder logic but in
reverse.

### test_protocol.py
Unit tests for protocol data integrity: verifies topic counts match array
lengths, checks byte position validity, and validates conversion function
mappings.

### test_decoder.py
Unit tests for decoding logic: tests individual conversion functions, validates
multi-byte decoding, and checks special case handling against known heatpump
responses.

### test_encoder.py
Unit tests for encoding logic: tests command generation, validates byte
positioning, and verifies checksums and special encoding rules.

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

