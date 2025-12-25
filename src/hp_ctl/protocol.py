# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class FieldSpec:
    """Specification for a message field."""

    name: str
    byte_offset: int
    bit_offset: Optional[int] = None
    bit_length: Optional[int] = None
    byte_length: Optional[int] = None
    converter: Optional[Callable[[int], Any]] = None
    inverse_converter: Optional[Callable[[Any], int]] = None
    unit: Optional[str] = None
    default: Any = None
    ha_class: Optional[str] = None
    ha_state_class: Optional[str] = None
    ha_icon: Optional[str] = None
    skip_zero: bool = True  # Skip 0x00 values (usually means no data)
    writable: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass
class Message:
    """Represents a decoded message with field values."""

    packet_type: int  # 0x10 for standard, 0x21 for extra
    fields: dict


class MessageCodec:
    """Encodes/decodes Message instances using FieldSpec definitions."""

    def __init__(self, fields: list[FieldSpec], user_limits: Optional[dict[str, Any]] = None):
        self.fields = fields
        self.user_limits = user_limits or {}

    def decode(self, raw_msg: bytes, packet_type: int) -> Message:
        """Decode a raw UART message into a Message object.

        Assumes the message has already been validated by the UART layer
        (length and checksum are correct).

        Args:
            raw_msg: Raw message bytes (pre-validated)
            packet_type: Packet type identifier (0x10 for standard, 0x21 for extra)

        Returns:
            Decoded Message object
        """
        logger.debug("Decoding message: %d bytes, packet_type: 0x%02x", len(raw_msg), packet_type)
        # Parse fields from data
        values = {}
        for field in self.fields:
            # Check if field fits in buffer
            max_offset = field.byte_offset + (field.byte_length or 1)
            if max_offset > len(raw_msg):
                logger.debug(
                    "Field %s: offset %d exceeds message length %d (skipping)",
                    field.name,
                    field.byte_offset,
                    len(raw_msg),
                )
                continue

            raw_value = self._extract_value(raw_msg, field)

            # Skip fields with 0x00 (no data available) if skip_zero is True
            if raw_value == 0 and field.skip_zero:
                logger.debug("Field %s: raw=0x0 (skipping - no data)", field.name)
                continue

            try:
                converted_value = field.converter(raw_value) if field.converter else raw_value
            except (ValueError, KeyError) as e:
                # Converter rejected the value (invalid/placeholder data)
                logger.debug("Field %s: raw=0x%x (skipping - %s)", field.name, raw_value, e)
                continue

            # Sanity check for temperature fields: skip if outside reasonable range
            if field.ha_class == "temperature" and isinstance(converted_value, (int, float)):
                if converted_value < -50 or converted_value > 100:
                    logger.debug(
                        "Field %s: raw=0x%x, converted=%s %s (skipping - out of range)",
                        field.name,
                        raw_value,
                        converted_value,
                        field.unit or "",
                    )
                    continue

            values[field.name] = converted_value
            logger.debug(
                "Field %s: raw=0x%x, converted=%s %s",
                field.name,
                raw_value,
                converted_value,
                field.unit or "",
            )

        # Log all converted values in a readable format
        lines = [f"{len(values)} fields:"]
        for name, value in values.items():
            unit = next((f.unit for f in self.fields if f.name == name), "") or ""
            unit_str = f" {unit}" if unit else ""
            lines.append(f"  {name:<30} {value}{unit_str}")
        logger.info("\n".join(lines))

        logger.debug("Message decoded successfully: %d fields", len(values))
        return Message(packet_type=packet_type, fields=values)

    def encode(self, message: Message, base_buffer: Optional[bytes] = None) -> bytes:
        """Encode a Message into binary data using field definitions.

        Creates a write command buffer by starting with a template of 0x00 bytes
        (or optional base_buffer) and setting only the fields that have values.

        Args:
            message: Message object with fields to encode base_buffer: Optional
            base buffer to modify (defaults to 0x00-filled template)

        Returns:
            Encoded bytes ready for UART transmission

        Raises:
            ValueError: If field value is out of valid range or field is not
            writable
        """
        if base_buffer is None:
            buffer = bytearray(110)
            # Sync, Length-2 (108), Destination, Packet Type (0x10)
            buffer[0:4] = bytes([0xF1, 0x6C, 0x01, 0x10])
        else:
            buffer = bytearray(base_buffer)

        # Encode each field from the message
        for field_name, value in message.fields.items():
            field = self._get_field_by_name(field_name)

            if not field.writable:
                raise ValueError(f"Field '{field_name}' is not writable")

            # Validate value is within range
            self._validate_field_value(field, value)

            # Convert user value to raw integer
            if field.inverse_converter:
                raw_value = field.inverse_converter(value)
            else:
                raw_value = int(value)

            # Pack value into buffer
            self._pack_value(buffer, field, raw_value)

        return bytes(buffer)

    def _get_field_by_name(self, name: str) -> FieldSpec:
        """Find field spec by name."""
        for field in self.fields:
            if field.name == name:
                return field
        raise ValueError(f"Unknown field: {name}")

    def _validate_field_value(self, field: FieldSpec, value: Any) -> None:
        """Validate that a value is within the field's valid range."""
        min_val = field.min_value
        max_val = field.max_value

        # Override with user limits if present
        if field.name in self.user_limits:
            user_field_limits = self.user_limits[field.name]
            if isinstance(user_field_limits, dict) and "max" in user_field_limits:
                max_val = user_field_limits["max"]

        if min_val is not None and value < min_val:
            raise ValueError(f"Field '{field.name}' value {value} is below minimum {min_val}")

        if max_val is not None and value > max_val:
            limit_type = "user-defined " if field.name in self.user_limits else ""
            raise ValueError(
                f"Field '{field.name}' value {value} exceeds {limit_type}maximum {max_val}"
            )

    def _pack_value(self, buffer: bytearray, field: FieldSpec, raw_value: int) -> None:
        """Pack a raw value into the buffer at the field's position."""
        if field.byte_length and field.byte_length > 1:
            # Multi-byte field - little-endian
            for i in range(field.byte_length):
                buffer[field.byte_offset + i] = (raw_value >> (i * 8)) & 0xFF
        elif field.bit_offset is not None and field.bit_length is not None:
            # Bit field - read-modify-write
            byte_val = buffer[field.byte_offset]
            mask = ((1 << field.bit_length) - 1) << field.bit_offset
            byte_val = (byte_val & ~mask) | ((raw_value << field.bit_offset) & mask)
            buffer[field.byte_offset] = byte_val
        else:
            # Single byte field
            buffer[field.byte_offset] = raw_value & 0xFF

    def _extract_value(self, data: bytes, field: FieldSpec) -> int:
        """Extract a value from binary data using field specification."""
        if field.byte_length and field.byte_length > 1:
            # Multi-byte field - little-endian by default
            raw_value = 0
            for i in range(field.byte_length):
                raw_value |= data[field.byte_offset + i] << (i * 8)
            logger.debug(
                "Extracted multi-byte field at offset %d (length %d, little-endian): 0x%x",
                field.byte_offset,
                field.byte_length,
                raw_value,
            )
            return raw_value

        byte_val = data[field.byte_offset]
        if field.bit_offset is not None and field.bit_length is not None:
            # Extract bits from byte_val
            mask = (1 << field.bit_length) - 1
            extracted = (byte_val >> field.bit_offset) & mask
            logger.debug(
                "Extracted bit field at offset %d, bits [%d:%d]: 0x%x",
                field.byte_offset,
                field.bit_offset,
                field.bit_offset + field.bit_length,
                extracted,
            )
            return extracted
        logger.debug("Extracted byte field at offset %d: 0x%x", field.byte_offset, byte_val)
        return byte_val


def temp_converter(value: int) -> float:
    """Convert temperature: value - 128"""
    return value - 128


def quiet_mode_converter(value: int) -> str:
    """Convert quiet mode bit pattern to mode name"""
    quiet_modes = {
        0b01001: "Off",
        0b01010: "Level 1",
        0b01011: "Level 2",
        0b01100: "Level 3",
        0b10001: "Scheduled",
    }
    return quiet_modes.get(value, f"Unknown({value})")


def frequency_converter(value: int) -> int:
    """Convert compressor frequency: value - 1"""
    return value - 1


def pump_flow_rate_converter(value: int) -> float:
    """Convert pump flow rate from 16-bit little-endian value.

    Byte 170 (low byte): integer part of flow rate
    Byte 169 (high byte): fractional part = (value - 1) / 256

    Formula: low_byte + (high_byte - 1) / 256
    """
    low_byte = value & 0xFF
    high_byte = (value >> 8) & 0xFF
    return low_byte + (high_byte - 1) / 256


def pump_speed_converter(value: int) -> int:
    """Convert pump speed: (value - 1) * 50"""
    return (value - 1) * 50


def hp_power_converter(value: int) -> int:
    """Convert heat pump power: value - 1"""
    return value - 1


def fan_speed_converter(value: int) -> int:
    """Convert fan motor speed: (value - 1) * 10"""
    return (value - 1) * 10


def pressure_converter(value: int) -> float:
    """Convert pressure from raw value to bar.

    Formula: ((value - 1) / 5) * 0.980665
    - First converts to kgf/cm²: (value - 1) / 5
    - Then converts kgf/cm² to bar: * 0.980665
    """
    kgf_cm2 = (value - 1) / 5
    return kgf_cm2 * 0.980665


def water_pressure_converter(value: int) -> float:
    """Convert water pressure from raw value to bar.

    Formula: (value - 1) / 50
    """
    return (value - 1) / 50


def hp_status_converter(value: int) -> str:
    """Convert heat pump on/off status from byte 4

    0x55 = heat pump off, 0x56 = heat pump on
    Other values: 0x96=Force DHW on, 0x65=Water pump on, 0x75=Air Purge, 0xF0=Pump Down

    Raises ValueError for invalid values (like 0x8a in no-data packets) to trigger filtering
    """
    status_map = {
        0x55: "Off",
        0x56: "On",
        0x96: "Force DHW",
        0x65: "Service: Water pump",
        0x75: "Service: Air purge",
        0xF0: "Service: Pump down",
    }
    if value not in status_map:
        raise ValueError(f"Invalid hp_status value: 0x{value:02x}")
    return status_map[value]


def defrost_converter(value: int) -> str:
    """Convert defrost status and 3-way valve from byte 111

    Right 2 bits: 3-Way Valve (0b10=DHW, 0b01=Room)
    Next 2 bits: Defrost state (0b01=not active, 0b10=active)
    """
    valve_bits = value & 0b11
    defrost_bits = (value >> 2) & 0b11

    valve = "DHW" if valve_bits == 0b10 else "Room" if valve_bits == 0b01 else "Unknown"
    defrost = "Active" if defrost_bits == 0b10 else "Inactive"

    return f"Valve:{valve}, Defrost:{defrost}"


def operating_mode_converter(value: int) -> str:
    """Convert operating mode from byte 6

    Bit 1: Zone2 (0=off, 1=on)
    Bit 2: Zone1 (0=off, 1=on)
    3rd & 4th bit: DHW (b01=off, b10=on)
    5th-8th bit: Mode (b0001=DHW only, b0010=Heat, b0011=Cool, b0110=Heat+Zone, b1001=Auto(Heat), b1010=Auto(Cool))
    """
    zone2 = value & 0b1
    zone1 = (value >> 1) & 0b1
    dhw_bits = (value >> 2) & 0b11
    mode_bits = (value >> 4) & 0b1111

    dhw_status = "on" if dhw_bits == 0b10 else "off"

    mode_map = {
        0b0001: "DHW only",
        0b0010: "Heat",
        0b0011: "Cool",
        0b0101: "Heat",  # Heat with zones
        0b0110: "Heat",  # Heat with zones
        0b0111: "Cool",  # Cool with zones
        0b1001: "Auto(Heat)",
        0b1010: "Auto(Cool)",
    }

    # Reject mode_bits 0 (Off) as it appears in no-data packets
    # Use compressor_frequency or hp_status to determine if HP is actually off
    if mode_bits not in mode_map:
        raise ValueError(f"Invalid operating_mode: mode_bits={mode_bits:04b}")

    mode = mode_map[mode_bits]

    zones = []
    if zone1:
        zones.append("Z1")
    if zone2:
        zones.append("Z2")
    zone_info = f" [{'+'.join(zones)}]" if zones else ""

    return f"{mode}{zone_info}, DHW {dhw_status}"


def temp_inverse_converter(value: float) -> int:
    """Convert temperature back to raw: value + 128"""
    return int(round(value + 128))


def quiet_mode_inverse_converter(value: int) -> int:
    """Convert quiet mode level (0-3) to raw bit pattern: (value + 1)"""
    return value + 1


def hp_status_inverse_converter(value: int) -> int:
    """Convert HP status (0=Off, 1=On) to raw write value (1=Off, 2=On)"""
    return value + 1


def operating_mode_inverse_converter(value: int) -> int:
    """Convert operating mode (0-6) to raw byte 6 value"""
    mapping = {0: 18, 1: 19, 2: 24, 3: 33, 4: 34, 5: 35, 6: 40}
    return mapping.get(value, 0)


STANDARD_FIELDS = [
    FieldSpec(
        name="quiet_mode",
        byte_offset=7,
        bit_offset=3,
        bit_length=5,
        converter=quiet_mode_converter,
        inverse_converter=quiet_mode_inverse_converter,
        unit="",
        ha_class="enum",
        ha_icon="mdi:fan",
        writable=True,
        min_value=0,
        max_value=3,
    ),
    FieldSpec(
        name="zone1_actual_temp",
        byte_offset=139,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="outdoor_temp",
        byte_offset=142,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="outlet_water_temp",
        byte_offset=144,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="compressor_frequency",
        byte_offset=166,
        converter=frequency_converter,
        unit="Hz",
        ha_class="frequency",
        ha_state_class="measurement",
        ha_icon="mdi:sine-wave",
    ),
    FieldSpec(
        name="dhw_target_temp",
        byte_offset=42,
        converter=temp_converter,
        inverse_converter=temp_inverse_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
        writable=True,
        min_value=40.0,
        max_value=75.0,
    ),
    FieldSpec(
        name="zone1_heat_target_temp",
        byte_offset=38,
        converter=temp_converter,
        inverse_converter=temp_inverse_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
        writable=True,
        min_value=20.0,
        max_value=65.0,
    ),
    FieldSpec(
        name="zone1_target_temp",
        byte_offset=147,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="inlet_water_temp",
        byte_offset=143,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="pump_flow_rate",
        byte_offset=170,
        byte_length=2,
        converter=pump_flow_rate_converter,
        unit="L/min",
        ha_class=None,
        ha_state_class="measurement",
        ha_icon="mdi:pump",
    ),
    FieldSpec(
        name="operating_mode",
        byte_offset=6,
        converter=operating_mode_converter,
        inverse_converter=operating_mode_inverse_converter,
        unit="",
        ha_class="enum",
        ha_icon="mdi:heating-coil",
        writable=True,
        min_value=0,
        max_value=6,
    ),
    FieldSpec(
        name="dhw_actual_temp",
        byte_offset=141,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="pump_speed",
        byte_offset=171,
        converter=pump_speed_converter,
        unit="RPM",
        ha_class=None,
        ha_state_class="measurement",
        ha_icon="mdi:pump",
    ),
    FieldSpec(
        name="hp_status",
        byte_offset=4,
        converter=hp_status_converter,
        inverse_converter=hp_status_inverse_converter,
        unit="",
        ha_class="enum",
        ha_icon="mdi:power",
        skip_zero=False,  # 0x00 might be a valid status value
        writable=True,
        min_value=0,
        max_value=1,
    ),
    FieldSpec(
        name="defrost_status",
        byte_offset=111,
        converter=defrost_converter,
        unit="",
        ha_class="enum",
        ha_icon="mdi:snowflake-melt",
    ),
    FieldSpec(
        name="hp_power",
        byte_offset=191,
        converter=hp_power_converter,
        unit="kW",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
    ),
    FieldSpec(
        name="fan1_motor_speed",
        byte_offset=173,
        converter=fan_speed_converter,
        unit="RPM",
        ha_class=None,
        ha_state_class="measurement",
        ha_icon="mdi:fan",
    ),
    FieldSpec(
        name="discharge_temp",
        byte_offset=155,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="indoor_piping_temp",
        byte_offset=157,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="outdoor_piping_temp",
        byte_offset=158,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="defrost_temp",
        byte_offset=159,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="eva_outlet_temp",
        byte_offset=160,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="bypass_outlet_temp",
        byte_offset=161,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="ipm_temp",
        byte_offset=162,
        converter=temp_converter,
        unit="°C",
        ha_class="temperature",
        ha_state_class="measurement",
        ha_icon="mdi:thermometer",
    ),
    FieldSpec(
        name="high_pressure",
        byte_offset=163,
        converter=pressure_converter,
        unit="bar",
        ha_class="pressure",
        ha_state_class="measurement",
        ha_icon="mdi:gauge",
    ),
    FieldSpec(
        name="low_pressure",
        byte_offset=164,
        converter=pressure_converter,
        unit="bar",
        ha_class="pressure",
        ha_state_class="measurement",
        ha_icon="mdi:gauge",
        skip_zero=False,
    ),
    FieldSpec(
        name="water_pressure",
        byte_offset=125,
        converter=water_pressure_converter,
        unit="bar",
        ha_class="pressure",
        ha_state_class="measurement",
        ha_icon="mdi:water-pump",
        skip_zero=False,
    ),
]

# Extra packet (0x21) fields - power measurements in Watts (16-bit little-endian)
EXTRA_FIELDS = [
    FieldSpec(
        name="heat_power_consumption",
        byte_offset=14,
        byte_length=2,
        unit="W",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
        skip_zero=False,
    ),
    FieldSpec(
        name="cool_power_consumption",
        byte_offset=16,
        byte_length=2,
        unit="W",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
        skip_zero=False,
    ),
    FieldSpec(
        name="dhw_power_consumption",
        byte_offset=18,
        byte_length=2,
        unit="W",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
        skip_zero=False,
    ),
    FieldSpec(
        name="heat_power_generation",
        byte_offset=20,
        byte_length=2,
        unit="W",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
        skip_zero=False,
    ),
    FieldSpec(
        name="cool_power_generation",
        byte_offset=22,
        byte_length=2,
        unit="W",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
        skip_zero=False,
    ),
    FieldSpec(
        name="dhw_power_generation",
        byte_offset=24,
        byte_length=2,
        unit="W",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
        skip_zero=False,
    ),
]

STANDARD_CODEC = MessageCodec(STANDARD_FIELDS)
EXTRA_CODEC = MessageCodec(EXTRA_FIELDS)


class HeatPumpProtocol:
    """Router for decoding different heat pump packet types."""

    def __init__(self, user_limits: Optional[dict[str, Any]] = None):
        self.standard_codec = MessageCodec(STANDARD_FIELDS, user_limits=user_limits)
        self.extra_codec = MessageCodec(EXTRA_FIELDS, user_limits=user_limits)

    def decode(self, raw_msg: bytes) -> Message:
        """Decode a heat pump message based on its packet type.

        Args:
            raw_msg: Raw message bytes (pre-validated by UART layer)

        Returns:
            Decoded Message object with appropriate fields

        Raises:
            ValueError: If packet type is unknown
        """
        if len(raw_msg) < 4:
            raise ValueError(f"Message too short: {len(raw_msg)} bytes")

        packet_type = raw_msg[3]

        if packet_type == 0x10:
            logger.debug("Decoding standard packet (0x10)")
            return self.standard_codec.decode(raw_msg, packet_type)
        elif packet_type == 0x21:
            logger.debug("Decoding extra packet (0x21)")
            return self.extra_codec.decode(raw_msg, packet_type)
        else:
            raise ValueError(f"Unknown packet type: 0x{packet_type:02x}")


PROTOCOL = HeatPumpProtocol()
