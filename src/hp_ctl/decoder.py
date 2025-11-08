from hp_ctl.message import Message


class Decoder:
    """Decodes Panasonic Aquarea UART protocol messages"""

    def decode(self, raw_message: bytes) -> Message:
        """
        Decode a raw UART message.

        Args:
            raw_message: Raw bytes from UART

        Returns:
            Decoded Message object

        Raises:
            ValueError: If message is invalid or checksum fails
        """
        raise NotImplementedError("Decoder not yet implemented")
