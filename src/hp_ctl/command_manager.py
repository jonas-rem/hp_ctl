# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Command manager for heat pump communication with protocol compliance.

Implements HeishaMon's sequential locking pattern:
- Only one command in-flight at a time
- Wait for response or 2s timeout before sending next command
- Setting commands have priority over periodic queries
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Hardcoded configuration
QUERY_INTERVAL = 30  # seconds between queries
RESPONSE_TIMEOUT = 2.0  # seconds to wait for response


class CommandManager:
    """Manages all heat pump commands with sequential locking.

    Ensures protocol compliance by:
    - Queuing all commands (setting commands and periodic queries)
    - Enforcing sequential transmission (one at a time)
    - Waiting for response or timeout before sending next command
    - Prioritizing setting commands over queries

    Hardcoded configuration:
    - Query interval: 30 seconds
    - Response timeout: 2 seconds
    - No startup delay (first query sent immediately)
    """

    def __init__(self, uart_transceiver) -> None:
        """Initialize command manager.

        Args:
            uart_transceiver: UART transceiver instance for sending commands.
        """
        self.uart = uart_transceiver
        self.query_command = self._build_query_command()
        self.extra_query_command = self._build_extra_query_command()

        # Command queue (FIFO for setting commands)
        self.command_queue: list[bytes] = []
        self._queue_lock = threading.Lock()

        # State tracking
        self.waiting_for_response = False
        self.pending_extra_query = False
        self.last_send_time: Optional[float] = None
        self.last_query_time: Optional[float] = None
        self._state_lock = threading.Lock()

        # Threading
        self._stop_event = threading.Event()
        self._manager_thread: Optional[threading.Thread] = None

        logger.debug(
            "CommandManager initialized (interval=%ds, timeout=%.1fs)",
            QUERY_INTERVAL,
            RESPONSE_TIMEOUT,
        )

    def _build_query_command(self) -> bytes:
        """Build the Panasonic query command (0x71 header).

        Query format from protocol reference:
        - Byte 0: 0x71 (query header, not 0xf1 for settings)
        - Byte 1: 0x6c (length - 2 = 108)
        - Byte 2: 0x01 (source)
        - Byte 3: 0x10 (packet type)
        - Bytes 4-109: 0x00 (all parameters zero for query)
        - Byte 110: checksum (calculated and added by UART layer)

        Returns:
            110-byte query command (without checksum).
        """
        buffer = bytearray(110)
        buffer[0] = 0x71  # Query header
        buffer[1] = 0x6C  # Length - 2 (108)
        buffer[2] = 0x01  # Source
        buffer[3] = 0x10  # Packet type
        # Rest is already 0x00 (query has no parameter changes)
        return bytes(buffer)

    def _build_extra_query_command(self) -> bytes:
        """Build the Panasonic extra query command (0x71 header, 0x21 type).

        Extra query format:
        - Byte 0: 0x71 (query header)
        - Byte 1: 0x6c (length - 2 = 108)
        - Byte 2: 0x01 (source)
        - Byte 3: 0x21 (packet type for power stats)
        - Bytes 4-109: 0x00
        - Byte 110: checksum (calculated and added by UART layer)

        Returns:
            110-byte query command (without checksum).
        """
        buffer = bytearray(self.query_command)
        buffer[3] = 0x21  # Packet type 0x21 (Extra)
        return bytes(buffer)

    def queue_command(self, encoded_bytes: bytes) -> None:
        """Queue a setting command (0xf1) to be sent.

        Setting commands are prioritized over periodic queries.

        Args:
            encoded_bytes: Complete 110-byte command (without checksum).
        """
        with self._queue_lock:
            self.command_queue.append(encoded_bytes)
            logger.debug("Command queued (queue_size=%d)", len(self.command_queue))

    def start(self) -> None:
        """Start command manager background thread.

        First query is sent immediately (no startup delay).
        """
        if self._manager_thread is not None and self._manager_thread.is_alive():
            logger.warning("CommandManager already running")
            return

        self._stop_event.clear()
        self._manager_thread = threading.Thread(
            target=self._manager_loop, daemon=True, name="Command-Manager"
        )
        self._manager_thread.start()
        logger.info("CommandManager started (interval=%ds)", QUERY_INTERVAL)

    def stop(self) -> None:
        """Stop command manager background thread."""
        logger.info("Stopping CommandManager")
        self._stop_event.set()
        if self._manager_thread:
            self._manager_thread.join(timeout=5)
        logger.info("CommandManager stopped")

    def on_response_received(self) -> None:
        """Called when any UART response is received.

        Unlocks waiting state to allow next command (HeishaMon pattern).
        """
        with self._state_lock:
            if self.waiting_for_response:
                self.waiting_for_response = False
                logger.debug("Response received, unlocked for next command")

    def _send_command(self, command_bytes: bytes, is_query: bool = False) -> None:
        """Send a command to heat pump.

        Args:
            command_bytes: Complete command bytes (without checksum).
            is_query: True if this is a periodic query (0x71), False for settings (0xf1).
        """
        try:
            self.uart.send(command_bytes)
            with self._state_lock:
                self.last_send_time = time.time()
                if is_query:
                    self.last_query_time = self.last_send_time
                    self.waiting_for_response = True
                else:
                    self.waiting_for_response = False
            cmd_type = "Query (0x71)" if is_query else "Setting (0xf1)"
            wait_str = "waiting for response" if is_query else "no response expected"
            logger.debug("%s sent, %s", cmd_type, wait_str)
        except Exception as e:
            logger.error("Failed to send command: %s", e)
            with self._state_lock:
                self.waiting_for_response = False

    def _check_timeout(self) -> None:
        """Check if response timeout has occurred."""
        with self._state_lock:
            if self.waiting_for_response and self.last_send_time is not None:
                elapsed = time.time() - self.last_send_time
                if elapsed >= RESPONSE_TIMEOUT:
                    logger.warning("Response timeout (%.1fs)", elapsed)
                    self.waiting_for_response = False

    def _should_send_query(self) -> bool:
        """Check if it's time to send periodic query.

        Returns:
            True if query should be sent, False otherwise.
        """
        with self._state_lock:
            if self.last_query_time is None:
                # First query - send immediately
                return True

            elapsed = time.time() - self.last_query_time
            return elapsed >= QUERY_INTERVAL

    def _manager_loop(self) -> None:
        """Background loop: process command queue and send periodic queries.

        Implements HeishaMon's sequential locking pattern:
        - Only one command in-flight at a time
        - Wait for response or timeout before next command
        - Setting commands have priority over queries
        """
        logger.debug("Command manager loop started")

        while not self._stop_event.is_set():
            try:
                # Check timeout first
                self._check_timeout()

                # Only process if not waiting for response
                can_send = False
                with self._state_lock:
                    can_send = not self.waiting_for_response

                if can_send:
                    # Priority 1: Process queued setting commands
                    command_to_send = None
                    with self._queue_lock:
                        if self.command_queue:
                            command_to_send = self.command_queue.pop(0)

                    if command_to_send:
                        self._send_command(command_to_send, is_query=False)
                        continue  # Skip to next iteration

                    # Priority 2: Send extra query if pending (requested after standard query)
                    send_extra = False
                    with self._state_lock:
                        if self.pending_extra_query:
                            send_extra = True
                            self.pending_extra_query = False

                    if send_extra:
                        self._send_command(self.extra_query_command, is_query=True)
                        continue

                    # Priority 3: Send periodic query if interval elapsed
                    if self._should_send_query():
                        with self._state_lock:
                            self.pending_extra_query = True
                        self._send_command(self.query_command, is_query=True)

            except Exception as e:
                logger.exception("Error in command manager loop: %s", e)

            # Sleep briefly to avoid busy-wait
            self._stop_event.wait(timeout=0.5)

        logger.debug("Command manager loop exited")
