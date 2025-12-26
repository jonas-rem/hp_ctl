# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from hp_ctl.main import Application
from hp_ctl.protocol import EXTRA_FIELDS, STANDARD_FIELDS


@pytest.fixture
def test_config(tmp_path):
    """Create a temporary config file for testing."""
    config = {
        "uart": {
            "port": "/dev/ttyUSB0",
            "baudrate": 9600,
        },
        "mqtt": {
            "broker": "localhost",
            "port": 1883,
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return str(config_file)


@pytest.fixture
def panasonic_test_message():
    """Load panasonic_answer test case from fixtures."""
    fixture_path = Path(__file__).parent / "fixtures" / "decoder_test_cases.yaml"
    with open(fixture_path, "r") as f:
        data = yaml.safe_load(f)

    case_data = data["test_cases"]["panasonic_answer"]
    raw_hex = case_data["raw_hex"].replace(" ", "").replace("\n", "")
    return bytes.fromhex(raw_hex)


class TestApp:
    """Integration tests for the complete application pipeline."""

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_app_init(self, mock_uart, mock_mqtt, test_config):
        """Test that application initializes correctly."""
        app = Application(config_path=test_config)

        assert app.config is not None
        assert app.config["uart"]["port"] == "/dev/ttyUSB0"
        assert app.config["mqtt"]["broker"] == "localhost"
        assert app.ha_mapper is not None

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_uart_decode_publish(
        self, mock_uart_class, mock_mqtt_class, test_config, panasonic_test_message
    ):
        """Test that UART message triggers decode and MQTT publish."""
        # Setup mocks
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart_class.return_value = MagicMock()

        # Create application
        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt

        # Simulate UART message
        app._on_uart_message(panasonic_test_message)

        # Verify state updates were published (discovery is now via on_connect callback)
        assert mock_mqtt.publish.call_count > 0

        # Check that state updates were published
        state_calls = [
            call for call in mock_mqtt.publish.call_args_list if "aquarea_k/state/" in str(call)
        ]
        assert len(state_calls) > 0

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_state_after_discovery(
        self, mock_uart_class, mock_mqtt_class, test_config, panasonic_test_message
    ):
        """Test that state updates are published after discovery."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart_class.return_value = MagicMock()

        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt

        # First message triggers discovery
        app._on_uart_message(panasonic_test_message)
        first_call_count = mock_mqtt.publish.call_count

        # Second message should only publish state updates (no new discovery)
        app._on_uart_message(panasonic_test_message)
        second_call_count = mock_mqtt.publish.call_count

        # Second message should have fewer calls (only state updates, no discovery)
        state_update_calls = second_call_count - first_call_count
        # Note: state_update_calls will only include fields from the standard packet (0x10)
        # since panasonic_test_message is a standard packet, not an extra packet
        assert state_update_calls <= len(STANDARD_FIELDS)

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_state_correct_values(
        self, mock_uart_class, mock_mqtt_class, test_config, panasonic_test_message
    ):
        """Test that state updates contain correct decoded values."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart_class.return_value = MagicMock()

        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt

        app._on_uart_message(panasonic_test_message)

        # Extract state update calls (those with aquarea_k/state/ in topic)
        state_calls = [
            call for call in mock_mqtt.publish.call_args_list if "aquarea_k/state/" in str(call)
        ]

        # Verify specific values from panasonic_answer test case
        state_dict = {call[0][0]: call[0][1] for call in state_calls}

        assert state_dict["aquarea_k/state/quiet_mode"] == "Off"
        assert state_dict["aquarea_k/state/zone1_actual_temp"] == "48"

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_invalid_msg_no_crash(self, mock_uart_class, mock_mqtt_class, test_config):
        """Test that invalid messages are handled gracefully."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart_class.return_value = MagicMock()

        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt

        # Send invalid message (too short)
        invalid_message = b"\x71\x05"

        # Should not raise exception
        app._on_uart_message(invalid_message)

        # Application should still be functional
        assert app.mqtt_client is not None

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_discovery_on_connect(self, mock_uart_class, mock_mqtt_class, test_config):
        """Test that discovery configs are published on MQTT connect."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart_class.return_value = MagicMock()

        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt

        # Simulate MQTT on_connect callback (as would happen in real connection)
        app._publish_discovery()

        # Count discovery publishes (homeassistant/sensor/...)
        discovery_calls = [
            call for call in mock_mqtt.publish.call_args_list if "homeassistant/sensor" in str(call)
        ]

        # Should have discovery calls for all fields
        all_fields = STANDARD_FIELDS + EXTRA_FIELDS
        assert len(discovery_calls) == len(all_fields)
        assert app.discovery_published

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_discovery_reconnect(self, mock_uart_class, mock_mqtt_class, test_config):
        """Test that discovery configs are re-published on MQTT reconnect."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart_class.return_value = MagicMock()

        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt

        # Simulate first connection
        app._publish_discovery()
        first_call_count = mock_mqtt.publish.call_count

        # Simulate reconnection (callback should publish again)
        app._publish_discovery()
        second_call_count = mock_mqtt.publish.call_count

        # Discovery should be published again on reconnection
        # Count includes standard fields (sensors) + writable fields
        # 33 sensors + 5 writable = 38
        assert second_call_count == first_call_count * 2
        # Count includes standard fields (sensors) + writable fields

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    def test_command_handling(self, mock_uart_class, mock_mqtt_class, test_config):
        """Test MQTT command handling."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_uart = MagicMock()
        mock_uart_class.return_value = mock_uart

        app = Application(config_path=test_config)
        app.mqtt_client = mock_mqtt
        app.uart_transceiver = mock_uart

        # Test valid command
        topic = "hp_ctl/aquarea_k/set/dhw_target_temp"
        payload = "48"
        app._on_mqtt_command(topic, payload)

        assert mock_uart.send.called
        # Verify encoded message (rough check)
        args = mock_uart.send.call_args[0][0]
        # Check standard packet type 0x10 at byte 3
        assert args[3] == 0x10
