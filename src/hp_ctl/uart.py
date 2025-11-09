import logging
import threading
import time
from typing import Callable, Optional

import serial

logger = logging.getLogger(__name__)


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
    ) -> None:
        """Initialize UART connection and callback for valid messages.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0').
            baudrate: Baud rate for serial communication. Defaults to 9600.
            on_message: Callback function invoked with validated message bytes.
        """
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.on_message = on_message  # Callback for validated messages
        self.listening = False
        self.thread: Optional[threading.Thread] = None

    def open(self) -> None:
        """Open UART connection."""
        self.serial_conn = serial.Serial(self.port, self.baudrate)

    def close(self) -> None:
        """Close UART connection and stop listening."""
        self.listening = False
        if self.thread:
            self.thread.join()
        if self.serial_conn:
            self.serial_conn.close()

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
        if not self.serial_conn:
            return b""

        # Wait for start delimiter (0x71)
        while True:
            byte = self.serial_conn.read(1)
            if not byte:
                return b""  # Connection closed or timeout
            if byte[0] == 0x71:
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
        # Minimum: start byte + length + data + checksum
        if len(message) < 4:
            return False
        # Byte 1 contains the length of the payload
        declared_length = message[1]
        # Expected: start(1) + length(1) + payload + checksum(1)
        return len(message) == 1 + 1 + declared_length + 1

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
            return False
        # Checksum is the last byte
        expected_checksum = message[-1]
        # Compute sum-based checksum of all bytes except the checksum
        data_sum = sum(message[:-1])
        computed_checksum = (256 - data_sum) & 0xFF
        return computed_checksum == expected_checksum

    def receive_and_validate(self) -> Optional[bytes]:
        """Receive a message and validate it.

        Returns:
            Validated message bytes, or None if validation fails.
        """
        message = self.read_message()
        if self.validate_length(message) and self.validate_crc(message):
            return message
        return None

    def start_listening(self, poll_interval: float = 0.1) -> None:
        """Start background listening thread to periodically check for data.

        Args:
            poll_interval: Time in seconds between polling attempts. Defaults to 0.1.
        """
        self.listening = True
        self.thread = threading.Thread(target=self._listen_loop, args=(poll_interval,))
        self.thread.start()

    def _listen_loop(self, poll_interval: float) -> None:
        """Background loop to check for data and emit via callback.

        Periodically checks for data every poll_interval seconds and invokes
        the on_message callback with validated messages.

        Args:
            poll_interval: Time in seconds between polling attempts.
        """
        while self.listening:
            try:
                message = self.receive_and_validate()
                if message and self.on_message:
                    self.on_message(message)
            except NotImplementedError:
                # Expected during development; re-raise to avoid silent failures
                raise
            except Exception as e:  # pylint: disable=broad-except
                logger.exception("UART error: %s", e)
            time.sleep(poll_interval)
