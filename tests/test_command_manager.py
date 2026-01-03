# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Unit tests for CommandManager."""

import time
from unittest.mock import Mock, patch

from hp_ctl.command_manager import CommandManager


class TestCommandManager:
    """Test suite for CommandManager class."""

    def test_query_command_format(self):
        """Verify query command has correct format (0x71 header)."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        # Check query command format
        assert len(cm.query_command) == 110
        assert cm.query_command[0] == 0x71  # Query header (not 0xf1)
        assert cm.query_command[1] == 0x6C  # Length - 2 (108)
        assert cm.query_command[2] == 0x01  # Source
        assert cm.query_command[3] == 0x10  # Packet type
        # All parameter bytes should be 0x00 for query
        assert all(b == 0x00 for b in cm.query_command[4:])

    def test_first_query_sent_immediately(self):
        """Verify first query is sent immediately (no startup delay)."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        # Start manager
        cm.start()

        # Give it a moment to start thread and send first query
        time.sleep(0.2)

        # Verify query was sent
        assert uart_mock.send.call_count >= 1
        first_call = uart_mock.send.call_args_list[0]
        assert first_call[0][0] == cm.query_command

        # Cleanup
        cm.stop()

    def test_query_interval_30s(self):
        """Verify queries are sent every 30 seconds."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        # Use patch to mock time.time
        with patch("hp_ctl.command_manager.time") as mock_time:
            mock_time.time.return_value = 0.0

            cm.start()
            time.sleep(0.1)  # Let thread start

            # First query at t=0
            assert uart_mock.send.call_count >= 1

            # Simulate response received to unlock state
            cm.on_response_received()

            # Advance time to 29s (not enough)
            mock_time.time.return_value = 29.0
            time.sleep(0.6)  # Wait for loop cycle
            first_count = uart_mock.send.call_count

            # Advance time to 31s (should trigger second query)
            mock_time.time.return_value = 31.0
            time.sleep(0.6)  # Wait for loop cycle
            second_count = uart_mock.send.call_count

            # Should have sent second query
            assert second_count > first_count

            cm.stop()

    def test_response_unlock(self):
        """Verify on_response_received() unlocks waiting state."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        # Simulate sending query
        cm._send_command(cm.query_command, is_query=True)
        assert cm.waiting_for_response is True

        # Simulate response received
        cm.on_response_received()
        assert cm.waiting_for_response is False

    def test_timeout_handling(self):
        """Verify timeout handling after 2 seconds."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        # Use patch to mock time
        with patch("hp_ctl.command_manager.time") as mock_time:
            # Send query at t=0
            mock_time.time.return_value = 0.0
            cm._send_command(cm.query_command, is_query=True)
            assert cm.waiting_for_response is True

            # Advance time to t=1.5 (not timeout yet)
            mock_time.time.return_value = 1.5
            cm._check_timeout()
            assert cm.waiting_for_response is True

            # Advance time to t=2.1 (timeout)
            mock_time.time.return_value = 2.1
            cm._check_timeout()
            assert cm.waiting_for_response is False

    def test_queue_command_prioritization(self):
        """Verify queued setting commands are prioritized over queries."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        setting_command = b"\xf1" + b"\x00" * 109

        # Mock time so query is due
        with patch("hp_ctl.command_manager.time") as mock_time:
            mock_time.time.return_value = 100.0
            cm.last_query_time = 50.0  # Last query was 50s ago, so due

            # Queue a setting command
            cm.queue_command(setting_command)

            # Process loop once
            cm.start()
            time.sleep(0.6)  # Wait for one loop iteration (0.5s sleep)

            # First command sent should be the setting command, not the query
            assert uart_mock.send.call_count >= 1
            assert uart_mock.send.call_args_list[0][0][0][0] == 0xF1

            cm.stop()

    def test_settings_no_lock(self):
        """Verify setting commands do NOT wait for response (fire-and-forget)."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        setting_command_1 = b"\xf1" + b"\x01" * 109
        setting_command_2 = b"\xf1" + b"\x02" * 109

        # Set last_query_time to now to prevent immediate query during test
        cm.last_query_time = time.time()

        cm.queue_command(setting_command_1)
        cm.queue_command(setting_command_2)

        cm.start()
        time.sleep(0.6)

        # First command sent
        assert uart_mock.send.call_count >= 1
        assert uart_mock.send.call_args_list[0][0][0] == setting_command_1
        # Should NOT be waiting for response
        assert cm.waiting_for_response is False

        # Second command should be sent almost immediately in next loop iteration
        time.sleep(0.6)
        assert uart_mock.send.call_count >= 2
        assert uart_mock.send.call_args_list[1][0][0] == setting_command_2

        cm.stop()

    def test_stop_gracefully(self):
        """Verify manager stops gracefully."""
        uart_mock = Mock()
        cm = CommandManager(uart_mock)

        cm.start()
        time.sleep(0.1)

        # Should be running
        assert cm._manager_thread is not None
        assert cm._manager_thread.is_alive()

        # Stop
        cm.stop()

        # Should have stopped
        assert not cm._stop_event.is_set() or not cm._manager_thread.is_alive()
