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

## Quick Start

### Prerequisites

- Python 3.12+
- MQTT broker running on localhost:1883 (or configure in `config.yaml`)
- Heat pump connected via UART (default: `/dev/ttyUSB0`)

### Architecture

- **`protocol.py`** - Message codec and field specifications
- **`uart.py`** - UART receiver with validation
- **`mqtt.py`** - MQTT client wrapper
- **`homeassistant.py`** - Home Assistant MQTT Discovery mapper
- **`main.py`** - Application orchestration with retry logic
- **`config.py`** - Configuration loader

### Configuration

Create a `config.yaml` file in the project root:

```yaml
uart:
  port: /dev/ttyUSB0
  baudrate: 9600

mqtt:
  broker: localhost
  port: 1883
```


### Development Setup

```bash
git clone <repository-url>
cd hp-ctl
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pip install tox
```

### Production Installation

#### System Service Installation

```bash
# Configure your settings
cp config.yaml.example config.yaml
nano config.yaml

# Run installation script
sudo ./install.sh

# Add service user to dialout group for UART access
sudo usermod -a -G dialout hpctl

# Start the service
sudo systemctl start hp-ctl

# Check status
sudo systemctl status hp-ctl

# View logs
sudo journalctl -u hp-ctl -f
```

The service will automatically start on boot.

#### Manual Installation

```bash
# Install from local
pip install .
# Install from Repository link
pip install -e git+https://github.com/jonas-rem/hp-ctl.git#egg=hp-ctl
```

### Starting the Application

```bash
# If installed as system service
sudo systemctl start hp-ctl

# If installed manually
python -m hp_ctl
# Or use the command directly
hp-ctl
```

The application will:
1. Connect to MQTT broker and UART device (retry every 3 s on connection fail)
2. Publish Home Assistant MQTT Discovery configs on first valid message
3. Continuously publish state updates to `{device_id}/state/{field}` topics

### Running Tests

#### With Tox

```bash
# Run all checks (tests, lint, type checking)
tox

# Run only tests
tox -e py

# Run with coverage
tox -e coverage
```

#### Directly with Pytest

```bash
# All tests
pytest

# Integration tests only
pytest tests/test_integration.py -v

# With coverage report
pytest --cov=hp_ctl --cov-report=html

# Type checking
mypy src/hp_ctl
```

## Logging

Adjust the log level in pyproject.toml.

## Code Quality

```bash
# Linting
ruff check hp_ctl tests

# Type checking
mypy hp_ctl
```

## Disclaimer

This is an independent open source project based on reverse-engineered protocol
analysis. It is **not affiliated with, endorsed by, or supported by Panasonic
Corporation**. Use at your own risk. Modifying or interfacing with your heat
pump may void your warranty. The authors assume no liability for any damage to
equipment or property.
