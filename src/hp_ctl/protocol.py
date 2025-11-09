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
    unit: Optional[str] = None
    default: Any = None
    ha_class: Optional[str] = None
    ha_state_class: Optional[str] = None
    ha_icon: Optional[str] = None


@dataclass
class Message:
    """Represents a decoded message with field values."""
    fields: dict


class MessageCodec:
    """Encodes/decodes Message instances using FieldSpec definitions."""

    def __init__(self, fields: list[FieldSpec]):
        self.fields = fields

    def decode(self, raw_msg: bytes) -> Message:
        """Decode a raw UART message into a Message object.

        Assumes the message has already been validated by the UART layer
        (length and checksum are correct).

        Args:
            raw_msg: Raw message bytes (pre-validated)

        Returns:
            Decoded Message object
        """
        logger.debug("Decoding message: %d bytes", len(raw_msg))
        # Parse fields from data
        values = {}
        for field in self.fields:
            raw_value = self._extract_value(raw_msg, field)
            converted_value = (
                field.converter(raw_value) if field.converter else raw_value
            )
            values[field.name] = converted_value
            logger.debug(
                "Field %s: raw=0x%x, converted=%s %s",
                field.name,
                raw_value,
                converted_value,
                field.unit or "",
            )

        logger.debug("Message decoded successfully: %d fields", len(values))
        return Message(fields=values)

    def encode(self, message: Message) -> bytes:
        """Encode a Message into binary data using field definitions."""
        raise NotImplementedError("encode() not yet implemented")

    def _extract_value(self, data: bytes, field: FieldSpec) -> int:
        """Extract a value from binary data using field specification."""
        if field.byte_length and field.byte_length > 1:
            # Multi-byte field (big-endian)
            raw_value = 0
            for i in range(field.byte_length):
                raw_value = (raw_value << 8) | data[field.byte_offset + i]
            logger.debug(
                "Extracted multi-byte field at offset %d (length %d): 0x%x",
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

def power_converter(value: int) -> float:
    """Convert power: (value - 1) / 5"""
    return (value - 1) / 5

MESSAGE_FIELDS = [
    FieldSpec(
        name="quiet_mode",
        byte_offset=7,
        bit_offset=3,
        bit_length=5,
        converter=quiet_mode_converter,
        unit="",
        ha_class="enum",
        ha_icon="mdi:fan",
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
        name="heat_power_consumption",
        byte_offset=193,
        converter=power_converter,
        unit="kW",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
    ),
    FieldSpec(
        name="heat_power_generation",
        byte_offset=194,
        converter=power_converter,
        unit="kW",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
    ),
    FieldSpec(
        name="dhw_power_consumption",
        byte_offset=197,
        converter=power_converter,
        unit="kW",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
    ),
    FieldSpec(
        name="dhw_power_generation",
        byte_offset=198,
        converter=power_converter,
        unit="kW",
        ha_class="power",
        ha_state_class="measurement",
        ha_icon="mdi:lightning-bolt",
    ),
]

MESSAGE_CODEC = MessageCodec(MESSAGE_FIELDS)
