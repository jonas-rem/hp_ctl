from hp_ctl.message import Message


class Decoder:
    """Decoder for Panasonic Aquarea Heatpump UART messages"""

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
        data = raw_msg[2 : 2 + msg_len]
        checksum = raw_msg[-1:]

        # Validate checksum
        calculated_checksum = self._calculate_checksum(raw_msg[:-1])
        if calculated_checksum != checksum[0]:
            raise ValueError(
                f"Invalid checksum: {checksum[0]:02x}, "
                f"expected {calculated_checksum:02x}"
            )

        # Parse quiet_mode from byte 7 (index 5 in data)
        if len(data) > 5:
            quiet_mode_byte = data[5]
            quiet_level = self._parse_quiet_level(quiet_mode_byte)
        else:
            quiet_level = 0

        return Message(
            len=msg_len,
            checksum=checksum,
            quiet_mode=quiet_level,
        )

    def _calculate_checksum(self, data: bytes) -> int:
        """Calculate checksum for message data.

        Checksum is calculated so that sum of all bytes (including checksum) & 0xFF == 0.
        checksum = (256 - sum(data_bytes)) & 0xFF
        """
        data_sum = sum(data) & 0xFF
        checksum = (256 - data_sum) & 0xFF
        return checksum

    def _parse_quiet_level(self, byte: int) -> int:
        """Parse quiet level from byte 7 (left 5 bits).

        Quiet levels:
        - 0b01001 (9) = Off
        - 0b01010 (10) = Level 1
        - 0b01011 (11) = Level 2
        - 0b01100 (12) = Level 3
        - 0b10001 (17) = Scheduled
        """
        quiet_bits = (byte >> 3) & 0x1F  # Extract left 5 bits
        return quiet_bits

    def _parse_power_mode(self, byte: int) -> int:
        """Parse power mode from byte 7 (right 3 bits).

        Power modes:
        - 0b001 (1) = Off
        - 0b010 (2) = 30 min
        - 0b011 (3) = 60 min
        - 0b100 (4) = 90 min
        """
        power_bits = byte & 0x07  # Extract right 3 bits
        return power_bits
