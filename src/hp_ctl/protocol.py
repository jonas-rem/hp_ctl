from dataclasses import dataclass
from typing import Any, Callable, Optional


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


@dataclass
class Message:
    """Represents a decoded message"""
    len: int
    checksum: bytes
    fields: dict


class MessageCodec:
    """Encodes/decodes Message instances using FieldSpec definitions."""

    def __init__(self, fields: list[FieldSpec]):
        self.fields = fields

    def decode(self, raw_msg: bytes) -> Message:
        """Decode a raw UART message into a Message object.

        Message format:
        - Bytes 0-1: Length (2 bytes, big-endian)
        - Bytes 2 to 2+len-1: Data
        - Last byte: Checksum

        Args:
            raw_msg: Raw message bytes

        Returns:
            Decoded Message object

        Raises:
            ValueError: If message format is invalid or checksum is incorrect
        """
        if len(raw_msg) < 4:
            raise ValueError(
                f"Invalid message len: {len(raw_msg)}, minimum 4"
            )

        msg_len = raw_msg[1]

        # Validate msg len: 2 (delim + len) + msg_len (data) + 1 (checksum)
        expected_total = 2 + msg_len + 1
        if len(raw_msg) != expected_total:
            raise ValueError(
                f"Invalid message len: {len(raw_msg)}, expected {expected_total}"
            )

        # Extract components
        checksum = raw_msg[-1:]

        # Validate checksum
        calculated_checksum = self._calculate_checksum(raw_msg[:-1])
        if calculated_checksum != checksum[0]:
            raise ValueError(
                f"Invalid checksum: {checksum[0]:02x}, "
                f"expected {calculated_checksum:02x}"
            )

        # Parse fields from data
        values = {}
        for field in self.fields:
            raw_value = self._extract_value(raw_msg, field)
            converted_value = (
                field.converter(raw_value) if field.converter else raw_value
            )
            values[field.name] = converted_value

        # Unpack parsed field values as kwargs to Message constructor
        # (e.g., quiet_mode from FieldSpec automatically maps to Message.quiet_mode)
        return Message(
            len=msg_len,
            checksum=checksum,
            fields=values,
        )

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
            return raw_value

        byte_val = data[field.byte_offset]
        if field.bit_offset is not None and field.bit_length is not None:
            # Extract bits from byte_val
            mask = (1 << field.bit_length) - 1
            return (byte_val >> field.bit_offset) & mask
        return byte_val

    def _calculate_checksum(self, data: bytes) -> int:
        """Calculate checksum for message data.

        Checksum is calculated so that sum of all bytes (including checksum) & 0xFF == 0.
        checksum = (256 - sum(data_bytes)) & 0xFF
        """
        data_sum = sum(data) & 0xFF
        checksum = (256 - data_sum) & 0xFF
        return checksum


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
    ),
    FieldSpec(
        name="zone1_actual_temp",
        byte_offset=139,
        converter=temp_converter,
        unit="°C",
    ),
    FieldSpec(
        name="heat_power_consumption",
        byte_offset=193,
        converter=power_converter,
        unit="kW",
    ),
    FieldSpec(
        name="heat_power_generation",
        byte_offset=194,
        converter=power_converter,
        unit="kW",
    ),
    FieldSpec(
        name="dhw_power_consumption",
        byte_offset=197,
        converter=power_converter,
        unit="kW",
    ),
    FieldSpec(
        name="dhw_power_generation",
        byte_offset=198,
        converter=power_converter,
        unit="kW",
    ),
]

MESSAGE_CODEC = MessageCodec(MESSAGE_FIELDS)
