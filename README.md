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

#### Optional: Field Value Limits

You can restrict maximum values for writable fields to prevent unsafe settings.
This is useful for limiting domestic hot water or heating temperatures beyond
the protocol's defaults.

```yaml
# Optional: Restrict maximum values for writable fields
limits:
  dhw_target_temp:
    max: 60  # °C (protocol allows up to 75°C)
  zone1_heat_target_temp:
    max: 50  # °C (protocol allows up to 65°C)
```

**Available writable fields:**
- `dhw_target_temp` - Domestic Hot Water target temperature (40-75°C)
- `zone1_heat_target_temp` - Zone 1 heating target temperature (20-65°C)
- `quiet_mode` - Quiet mode level (0-3)
- `operating_mode` - Operating mode (0-6)
- `hp_status` - Heat pump on/off status (0-1)

**Notes:**
- The `limits` section is optional. Omitted fields use protocol defaults.
- User-defined max values cannot exceed protocol maximums.
- Invalid configurations will raise an error on startup.

### Development Setup

```bash
git clone <repository-url>
cd hp-ctl
python3 -m venv venv
source venv/bin/activate
make install
```

### Production Installation

#### User Service Installation (Recommended)

The installation script sets up hp-ctl as a user service and installs udev
rules for USB device access.

```bash
# Configure your settings
cp config.yaml.example config.yaml
vim config.yaml

# Run installation script
./install.sh

# Replug your USB serial device

# Start the service
systemctl --user start hp-ctl

# Check status
systemctl --user status hp-ctl

# View logs
journalctl --user -u hp-ctl -f
```

**What gets installed:**
- User service in `~/.config/systemd/user/` (no sudo needed for management)
- Configuration in `~/.config/hp-ctl/config.yaml`
- udev rules creating `/dev/ttyUSB_custom` with MODE=0666 (world-readable/writable)
- Auto-start on boot via `loginctl enable-linger`

**Home Assistant Integration:**

The service automatically creates entities in Home Assistant using **MQTT
Discovery**.

- **Sensors:** All readable fields (temperatures, pressures, flow rates) appear
  as sensors.
- **Controls:** Writable fields appear as controllable entities:
    - **Climate/Switch:** `hp_status` (On/Off)
    - **Select:** `operating_mode` (Heat, Cool, DHW, etc.), `quiet_mode`
      (Level 1-3)
    - **Number:** `dhw_target_temp`, `zone1_heat_target_temp`

**No manual configuration in Home Assistant is required.** Just ensure the MQTT
integration is set up and "Enable Discovery" is checked (this is the default).
Controls in the Home Assistant UI will automatically send commands back to the
heat pump.

The service automatically retries MQTT broker connection every 3 seconds until
successful:

- **At boot:** If Home Assistant isn't ready, hp-ctl keeps retrying until
  connection succeeds
- **After HA restart:** Automatically reconnects and re-publishes device
  discovery configs
- **Zero manual intervention:** All reconnection logic is automatic

When you set up Home Assistant as a systemd user service, you can optimize
startup ordering:
1. Edit `~/.config/systemd/user/hp-ctl.service`
2. Uncomment the lines referencing `home-assistant.service`
3. Run `systemctl --user daemon-reload`

The service will automatically start on boot and run as your user. You can
manage it without sudo:

```bash
# Start/stop/restart
systemctl --user start hp-ctl
systemctl --user stop hp-ctl
systemctl --user restart hp-ctl

# Enable/disable auto-start
systemctl --user enable hp-ctl
systemctl --user disable hp-ctl

# View logs
journalctl --user -u hp-ctl -f
```

Configuration file location: `~/.config/hp-ctl/config.yaml`

#### Manual Installation

```bash
# Install from local
pip install .
# Install from Repository link
pip install -e git+https://github.com/jonas-rem/hp-ctl.git#egg=hp-ctl
```

### Starting the Application

```bash
# If installed as user service
systemctl --user start hp-ctl

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

```bash
make test                # Run all tests
make check               # Lint + type checking
make coverage            # Test with coverage report
make fix                 # Auto-fix lint issues

# Run a single test
pytest tests/test_protocol.py::test_temp_converter
```

## Logging

All logs are sent to systemd journal when running as a service:

```bash
# Follow live logs
journalctl --user -u hp-ctl -f

# Last 100 lines
journalctl --user -u hp-ctl -n 100

# Logs since boot
journalctl --user -u hp-ctl -b
```

The log level can be adjusted in `src/hp_ctl/main.py` (`LOGLEVEL` constant).

## Disclaimer

This is an independent open source project based on reverse-engineered protocol
analysis. It is **not affiliated with, endorsed by, or supported by Panasonic
Corporation**. Use at your own risk. Modifying or interfacing with your heat
pump may void your warranty. The authors assume no liability for any damage to
equipment or property.
