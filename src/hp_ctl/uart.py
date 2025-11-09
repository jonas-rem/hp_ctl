import logging
import threading
import time
from typing import Callable, Optional

import serial

logger = logging.getLogger(__name__)

# Protocol constants
START_DELIMITER = 0x71
MESSAGE_MIN_LENGTH = 6


class UartReceiver:
    """UART receiver for background listening and message validation.

    Handles delimiter detection, length validation, and CRC checking.
    Emits valid messages via callback.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        on_message: Optional[Callable[[bytes], None]] = None,
        poll_interval: float = 0.1,
    ) -> None:
        """Initialize UART connection and start listening.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0').
            baudrate: Baud rate for serial communication. Defaults to 9600.
            on_message: Callback function invoked with validated message bytes.
            poll_interval: Time in seconds between polling attempts. Defaults to 0.1.
        """
        self.port = port
        self.baudrate = baudrate
        self.on_message = on_message
        self.poll_interval = poll_interval
        self.listening = True
        logger.debug("Opening UART connection: %s at %d baud", port, baudrate)
        self.serial_conn = serial.Serial(port, baudrate)
        logger.info("UART connection opened: %s", port)
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        logger.debug("Listening thread started")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *args):
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close UART connection and stop listening."""
        logger.debug("Closing UART connection")
        self.listening = False
        self.thread.join(timeout=1.0)
        self.serial_conn.close()
        logger.info("UART connection closed")

    def read_message(self) -> bytes:
        """Read a complete message from UART.

        Implements delimiter-based framing:
        - Waits for 0x71 start delimiter
        - Reads length byte
        - Reads payload and checksum
        - Returns complete framed message

        Returns:
            Complete message bytes (delimiter + length + payload + checksum),
            or empty bytes if connection is closed or timeout occurs.
        """

        # Wait for start delimiter
        while True:
            byte = self.serial_conn.read(1)
            if not byte:
                return b""
            if byte[0] == START_DELIMITER:
                break

        # Read length byte
        length_byte = self.serial_conn.read(1)
        if not length_byte:
            return b""  # Connection closed or timeout

        declared_length = length_byte[0]
        # Read payload and checksum (declared_length bytes + 1 checksum byte)
        payload_and_checksum = self.serial_conn.read(declared_length + 1)
        if len(payload_and_checksum) != declared_length + 1:
            return b""  # Incomplete message

        # Assemble complete message: delimiter + length + payload + checksum
        return byte + length_byte + payload_and_checksum

    def validate_length(self, message: bytes) -> bool:
        """Validate packet length.

        Checks that the message has a minimum length and that the declared
        length matches the actual message length.

        Args:
            message: Message bytes to validate.

        Returns:
            True if length is valid, False otherwise.
        """
        if len(message) < MESSAGE_MIN_LENGTH:
            logger.warning("Length validation failed: message too short (%d bytes)", len(message))
            return False
        # Expected: start(1) + length(1) + payload + checksum(1)
        valid = len(message) == 3 + message[1]
        if not valid:
            logger.warning("Length validation failed: declared=%d, actual=%d", message[1], len(message) - 3)
        return valid

    def validate_crc(self, message: bytes) -> bool:
        """Validate CRC.

        Computes and verifies the checksum of the message. The checksum is
        calculated so that the sum of all bytes (including checksum) & 0xFF == 0.
        Formula: checksum = (256 - sum(data_bytes)) & 0xFF

        Args:
            message: Message bytes to validate.

        Returns:
            True if CRC is valid, False otherwise.
        """
        if len(message) < 2:
            logger.warning("CRC validation failed: message too short")
            return False
        # Checksum is the last byte
        expected_checksum = message[-1]
        # Compute sum-based checksum of all bytes except the checksum
        data_sum = sum(message[:-1])
        computed_checksum = (256 - data_sum) & 0xFF
        valid = computed_checksum == expected_checksum
        if not valid:
            logger.warning("CRC validation failed: expected=0x%02x, computed=0x%02x", expected_checksum, computed_checksum)
        return valid

    def receive_and_validate(self) -> Optional[bytes]:
        """Receive a message and validate it.

        Returns:
            Validated message bytes, or None if validation fails.
        """
        message = self.read_message()
        if self.validate_length(message) and self.validate_crc(message):
            logger.debug("Message parsed: %s", message.hex())
            return message
        return None


    def _listen_loop(self) -> None:
        """Background loop to check for data and emit via callback.

        Periodically checks for data and invokes the on_message callback
        with validated messages.
        """
        while self.listening:
            try:
                message = self.receive_and_validate()
                if message and self.on_message:
                    logger.debug("Invoking callback with message")
                    self.on_message(message)
            except NotImplementedError:
                # Expected during development; re-raise to avoid silent failures
                raise
            except Exception as e:  # pylint: disable=broad-except
                logger.exception("UART error: %s", e)
            time.sleep(self.poll_interval)
