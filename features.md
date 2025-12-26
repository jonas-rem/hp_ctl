# hp-ctl Features Documentation

This document describes the current implementation and planned features of hp-ctl,
a Python service for controlling Panasonic Aquarea heat pumps via UART with MQTT
integration and Home Assistant discovery.

---

## Part 1: Current Implementation

### Overview

hp-ctl is a standalone Linux service that interfaces with Panasonic Aquarea heat
pumps over UART, providing bidirectional communication for both monitoring and
control. All data is published via MQTT with automatic Home Assistant discovery,
enabling seamless integration without manual configuration.

**Key Design Principles:**
- Robust retry logic for network resilience
- Type-safe protocol implementation with full test coverage
- Standalone operation with optional HA integration
- User-configurable safety limits

### Core Features

#### 1. UART Communication

**Bidirectional Serial Interface:**
- Read heat pump state updates (every ~5 seconds)
- Send control commands to heat pump
- Automatic checksum validation
- Graceful error handling and recovery

**Module:** `src/hp_ctl/uart.py`
- `UartTransceiver` class for send/receive operations
- Callback-based message delivery
- Configurable poll interval (default: 100ms)

#### 2. Protocol Encoding/Decoding

**Message Types:**
- `0x10` - Standard fields (temperatures, pressures, operating state)
- `0x21` - Extended fields (advanced diagnostics)

**40+ Monitored Fields:**
- Temperatures (zone, outdoor, DHW, inlet/outlet water)
- Compressor frequency and power
- Pump speed and flow rate
- Pressures (refrigerant, water)
- Operating modes and status

**Module:** `src/hp_ctl/protocol.py`
- `FieldSpec` dataclass for field definitions
- `MessageCodec` for encode/decode operations
- Converter functions with validation
- Skip logic for invalid/placeholder values

#### 3. MQTT Publishing

**State Updates:**
- Topic format: `hp_ctl/{device_id}/state/{field_name}`
- Published on every valid UART message
- Retain flag for persistent state

**Connection Management:**
- Automatic reconnection with 3s retry interval
- Graceful handling of broker unavailability
- Re-publishes discovery configs on reconnect

**Module:** `src/hp_ctl/mqtt.py`
- Wrapper around paho-mqtt
- Callback support for connect/message events
- Subscribe/publish helpers

#### 4. Home Assistant Discovery

**Automatic Entity Creation:**
- **Sensors** (read-only): All temperature, pressure, flow, frequency fields
- **Numbers** (writable): `dhw_target_temp`, `zone1_heat_target_temp`
- **Selects** (writable): `operating_mode`, `quiet_mode`
- **Switches** (writable): `hp_status` (On/Off)

**Discovery Topic Format:**
- `homeassistant/{component}/{device_id}/{field}/config`

**Device Grouping:**
- All entities grouped under single device: "Aquarea Heat Pump"
- Consistent naming and iconography
- Appropriate device classes (temperature, pressure, etc.)

**Module:** `src/hp_ctl/homeassistant.py`
- `HomeAssistantMapper` generates discovery payloads
- Automatic min/max/step configuration for numbers
- Option lists for selects

#### 5. Command Handling

**Writable Fields (5 total):**

| Field                    | Type   | Range                          | Description             |
|--------------------------|--------|--------------------------------|-------------------------|
| `hp_status`              | Select | On/Off                         | Power state             |
| `operating_mode`         | Select | Heat, Cool, Auto, DHW, +DHW    | Operating mode          |
| `quiet_mode`             | Select | Off, Level 1, Level 2, Level 3 | Noise reduction         |
| `dhw_target_temp`        | Number | 40-75°C                        | Domestic hot water      |
| `zone1_heat_target_temp` | Number | 20-65°C                        | Heating water target    |

**Command Flow:**
1. Home Assistant sends command to `hp_ctl/{device_id}/set/{field}`
2. hp-ctl validates command against field spec
3. Encodes command into binary packet (type `0x10`)
4. Sends via UART to heat pump
5. Heat pump acknowledges and updates state
6. State update published back to MQTT

**Module:** `src/hp_ctl/main.py`
- `_on_mqtt_command()` handles incoming commands
- Automatic type conversion (string -> int/enum)
- Error logging for invalid commands

#### 6. User-Configurable Limits

**Safety Override in config.yaml:**
```yaml
limits:
  dhw_target_temp:
    max: 60  # Override protocol default (75°C)
  zone1_heat_target_temp:
    max: 50  # Override protocol default (65°C)
```

**Validation:**
- User limits cannot exceed protocol maximums
- Applied to both encoding and HA discovery
- Invalid configs raise errors on startup

#### 7. Application Orchestration

**Main Loop:** `src/hp_ctl/main.py`
- Initializes MQTT and UART with retry logic
- Coordinates message flow between components
- Signal handling (SIGINT, SIGTERM) for graceful shutdown
- Publishes discovery configs on every connection

**Retry Behavior:**
- MQTT/UART connection failures retry every 3 seconds
- Infinite retries by default (configurable)
- Automatic recovery after broker/device restarts

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         main.py                             │
│  Application orchestration, retry logic, signal handling    │
└──────────┬──────────────────────────────────────┬───────────┘
           │                                      │
    ┌──────▼──────┐                        ┌──────▼──────┐
    │  uart.py    │                        │  mqtt.py    │
    │ UartTrx     │                        │ MqttClient  │
    └──────┬──────┘                        └──────┬──────┘
           │                                      │
    ┌──────▼─────────────────────────────────────▼──────┐
    │              protocol.py                          │
    │  FieldSpec, MessageCodec, converters              │
    └───────────────────────┬───────────────────────────┘
                            │
                   ┌────────▼────────┐
                   │ homeassistant.py│
                   │ HAMapper        │
                   └─────────────────┘
                            │
                   ┌────────▼────────┐
                   │   config.py     │
                   │ YAML loader     │
                   └─────────────────┘
```

### Current Capabilities Summary

**Implemented:**
- Bidirectional UART communication
- Full protocol encode/decode (standard + extended fields)
- MQTT state publishing
- Home Assistant automatic discovery
- Command handling (5 writable fields)
- User-configurable safety limits
- Robust retry and reconnection logic
- Comprehensive test suite (pytest)
- Production systemd service setup

---

## Part 2: Planned Feature - Intelligent Heat Demand Control

### Vision

An autonomous heating optimization system that maximizes heat pump efficiency by
matching heat output to actual demand based on outdoor temperature. The system
operates standalone within hp-ctl but can be monitored and adjusted via Home
Assistant.

### Problem Statement

Heat pumps are most efficient when running at low compressor frequencies for
extended periods. However, typical thermostatic control causes:

1. **High-power bursts:** Large temperature differentials trigger high compressor
   frequency to "catch up" quickly
2. **Short cycling:** Frequent on/off cycles reduce efficiency and increase wear
3. **Suboptimal COP:** High-frequency operation significantly reduces the
   coefficient of performance

### Solution Goals

1. **Efficiency First:** Prefer low-power, long-runtime operation over high-power
   short bursts. Run the heat pump for more hours per day at lower compressor
   frequency rather than fewer hours at high frequency.

2. **Standalone Operation:** Works without Home Assistant once configured. If HA
   crashes or has issues, heating continues to function normally in automatic
   mode.

3. **Demand-Based Control:** Adjusts daily heating output based on outdoor
   temperature using a user-defined mapping table.

4. **Gradual Temperature Ramping:** Smooth temperature target adjustments to keep
   compressor frequency low. Always set target temperature slightly above current
   outlet water temperature.

5. **Time-Aware:** Respects configurable blackout periods when the heat pump
   should not run (e.g., night hours, early morning).

6. **Observable and Adjustable:** Status and controls exposed via MQTT for HA
   integration. Users can fine-tune with a relative temperature offset (-3 to +3
   degrees).

### Core Concept

Instead of maintaining a fixed target temperature, the system:

1. Estimates daily heat demand from outdoor temperature (user-defined mapping)
2. Calculates target runtime hours to deliver required heat
3. Gradually increases `zone1_heat_target_temp` just above current
   `outlet_water_temp`
4. Keeps compressor frequency low (efficient operating zone)
5. Runs longer hours at lower power instead of short high-power bursts

**Example Scenario:**
- Outdoor temp: 5°C → Daily demand: 30 kWh (from config table)
- Current outlet temp: 38°C → Set target to 39°C
- Heat pump runs at ~30 Hz (efficient) for 6 hours
- Alternative without optimization: 60 Hz for 3 hours (less efficient)
- As day progresses and demand is met, system adjusts accordingly

### Configuration Design

**New section in config.yaml:**

```yaml
automation:
  # Enable/disable automation feature
  enabled: true

  # Default mode on startup: manual | automatic
  mode: automatic

  # Outdoor temperature to daily heat demand mapping
  # System interpolates between points for intermediate temperatures
  heat_demand_map:
    - outdoor_temp: -10  # °C
      daily_kwh: 50      # kWh required per day
    - outdoor_temp: 0
      daily_kwh: 35
    - outdoor_temp: 5
      daily_kwh: 30
    - outdoor_temp: 10
      daily_kwh: 20
    - outdoor_temp: 15
      daily_kwh: 10

  # Time periods when heat pump should not run
  # Static configuration, not overridable at runtime
  blackout_periods:
    - start: "23:00"
      end: "05:00"

  # Temperature ramping behavior
  temperature_ramping:
    step_size: 0.5           # °C to increase per adjustment
    interval: 300            # seconds between adjustments
    offset_above_outlet: 1.0 # Target = outlet_temp + offset

  # Safety limits
  limits:
    max_outlet_temp: 55      # Never exceed this outlet temp
```

### MQTT Interface

**Control Topics (hp-ctl subscribes to these):**

| Topic | Payload | Description |
|-------|---------|-------------|
| `hp_ctl/aquarea_k/automation/mode/set` | `manual` or `automatic` | Switch control mode |
| `hp_ctl/aquarea_k/automation/temp_offset/set` | `-3` to `+3` | Relative temp adjustment |

**Status Topics (hp-ctl publishes these):**

| Topic | Payload | Description |
|-------|---------|-------------|
| `hp_ctl/aquarea_k/automation/mode` | `manual` or `automatic` | Current mode |
| `hp_ctl/aquarea_k/automation/temp_offset` | `-3` to `+3` | Current offset |
| `hp_ctl/aquarea_k/automation/status` | JSON object | Detailed status |

**Automation Status JSON:**
```json
{
  "outdoor_temp": 5.2,
  "estimated_demand_kwh": 29.5,
  "target_runtime_hours": 6.2,
  "actual_runtime_today_hours": 3.1,
  "calculated_target_temp": 42.0,
  "active_target_temp": 43.0,
  "in_blackout": false,
  "last_adjustment": "2025-12-26T14:30:00Z"
}
```

**Note:** Automation topics are clearly separated from heat pump state topics
(`hp_ctl/.../automation/...` vs `hp_ctl/.../state/...`) so users know these are
hp-ctl features, not native heat pump properties.

### High-Level Control Algorithm

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTROL LOOP (every N seconds)           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Check blackout  │
                    │    period       │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
       ┌────────────┐                ┌────────────┐
       │ IN BLACKOUT│                │  ACTIVE    │
       │ Set HP=Off │                │  Continue  │
       │ Wait next  │                │  Control   │
       └────────────┘                └──────┬─────┘
                                            │
                              ┌─────────────┴─────────────┐
                              ▼                           │
                    ┌─────────────────┐                   │
                    │ Read state from │                   │
                    │ MQTT topics:    │                   │
                    │ - outdoor_temp  │                   │
                    │ - outlet_temp   │                   │
                    │ - hp_status     │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Calculate heat  │                   │
                    │ demand from     │                   │
                    │ outdoor temp    │                   │
                    │ (interpolate)   │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Calculate       │                   │
                    │ target runtime  │                   │
                    │ hours today     │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Get actual      │                   │
                    │ runtime today   │                   │
                    │ (self-tracked)  │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Calculate new   │                   │
                    │ target temp:    │                   │
                    │ outlet + offset │                   │
                    │ + user offset   │                   │
                    │ + progress adj  │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Apply safety    │                   │
                    │ limits (clamp)  │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Send command if │                   │
                    │ target changed  │                   │
                    └────────┬────────┘                   │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐                   │
                    │ Publish status  │                   │
                    │ to MQTT         │◀──────────────────┘
                    └─────────────────┘
```

### Data Flow Architecture

```
┌──────────────────┐
│  UART Messages   │──┐
│  (from HP)       │  │
└──────────────────┘  │
                      ▼
                ┌─────────────┐
                │  protocol   │
                │   decode    │
                └──────┬──────┘
                       │
                       ▼
                ┌─────────────┐         ┌──────────────────┐
                │    MQTT     │────────▶│  Home Assistant  │
                │   publish   │         │   (optional)     │
                └──────┬──────┘         └────────┬─────────┘
                       │                         │
                       │ subscribe to            │ user adjusts
                       │ own state topics        │ mode/offset
                       ▼                         │
            ┌──────────────────────┐             │
            │ AutomationController │◀────────────┘
            │                      │
            │  Components:         │
            │  - HeatDemandCalc    │
            │  - RuntimeTracker    │
            │  - TempController    │
            │  - BlackoutScheduler │
            └──────────┬───────────┘
                       │
                       │ calculated control commands
                       ▼
                ┌─────────────┐
                │    MQTT     │
                │ set command │
                └──────┬──────┘
                       │
                       ▼
                ┌─────────────┐
                │  protocol   │
                │   encode    │
                └──────┬──────┘
                       │
                       ▼
                ┌─────────────┐
                │    UART     │
                │   send      │──────▶  Heat Pump
                └─────────────┘
```

### Key Design Decisions

#### Runtime Tracking: Self-Contained via MQTT

hp-ctl subscribes to its own `hp_status` topic to track on/off transitions.
This approach:
- Keeps architecture clean (no HA API dependency)
- Works standalone without external data sources
- Uses existing MQTT infrastructure
- Resets daily at midnight

#### Mode Control: MQTT Topics with HA Discovery

- Automation mode (`manual`/`automatic`) exposed as HA Select entity
- Temperature offset exposed as HA Number entity (-3 to +3)
- Both clearly marked as "hp-ctl automation" features in HA
- Startup mode configurable in config.yaml

#### Blackout Periods: Static Configuration

- Defined in config.yaml, not overridable at runtime
- Simple time ranges (start/end)
- No exceptions or bypasses
- Heat pump set to Off during blackout

#### Heat Demand Mapping: User-Defined Table

- 5+ data points mapping outdoor temp to daily kWh
- Linear interpolation between points
- User calibrates based on their home's characteristics
- Can be refined over time based on observed behavior

### Safety Considerations

1. **Manual Mode Override:**
   - Switching to manual immediately stops automatic control
   - User has full direct control via HA
   - Automatic mode can be re-enabled anytime

2. **Configuration Validation:**
   - Heat demand map must have at least 2 points
   - Temperatures in ascending order
   - Blackout periods must be valid time ranges
   - Errors on startup for invalid config

3. **Limit Enforcement:**
   - Never exceed `max_outlet_temp`
   - All calculated values clamped to safe ranges
   - Respects user-defined limits from main config

4. **Graceful Degradation:**
   - If outdoor_temp unavailable: use last known value
   - If MQTT disconnected: pause automation until reconnect
   - If UART unavailable: log error, retry

5. **Blackout Hard Stop:**
   - No commands sent during blackout periods
   - Heat pump set to Off if currently running
   - Queued commands discarded

### Home Assistant Integration

**Entities Created for Automation:**

| Entity | Type | Description |
|--------|------|-------------|
| `select.aquarea_automation_mode` | Select | Manual/Automatic mode |
| `number.aquarea_automation_temp_offset` | Number | -3 to +3°C adjustment |
| `sensor.aquarea_automation_status` | Sensor | JSON status with attributes |

**Dashboard Integration:**
- Mode selector for switching manual/automatic
- Slider for temperature offset adjustment
- Status sensor showing current automation state
- All existing sensors (outdoor temp, outlet temp, etc.) remain available

### Implementation Approach

**New Module:** `src/hp_ctl/automation.py`

**Components to Implement:**
1. **HeatDemandCalculator** - Interpolates demand from outdoor temp mapping
2. **RuntimeTracker** - Monitors hp_status transitions, tracks daily runtime
3. **TemperatureController** - Calculates target temp with ramping logic
4. **BlackoutScheduler** - Checks if current time is in blackout period
5. **AutomationController** - Main orchestration, runs control loop

**Integration Points:**
- Hooks into `main.py` for MQTT callbacks
- Subscribes to automation command topics
- Publishes automation status topics
- Uses existing protocol layer for encoding commands

## Summary

hp-ctl currently provides a robust, production-ready interface for Panasonic
Aquarea heat pumps with bidirectional UART control, MQTT publishing, and seamless
Home Assistant integration.

The planned automation feature will add intelligent demand-based heating control
that prioritizes efficiency by running the heat pump at low power for extended
periods rather than high-power short bursts. The system operates standalone once
configured, ensuring reliable heating even when Home Assistant is unavailable,
while still providing convenient monitoring and adjustment capabilities through
HA when desired.
