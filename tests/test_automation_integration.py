# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Integration tests for automation discovery and publishing."""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from hp_ctl.main import Application


@pytest.fixture
def automation_config(tmp_path):
    """Create a temporary config file with automation enabled."""
    config = {
        "uart": {"port": "/dev/ttyUSB0", "baudrate": 9600},
        "mqtt": {"broker": "localhost", "port": 1883},
        "automation": {
            "enabled": True,
            "weather": {"latitude": 52.52, "longitude": 13.41},
            "heat_demand_map": [
                {"outdoor_temp": 0, "daily_kwh": 35},
                {"outdoor_temp": 10, "daily_kwh": 20},
            ],
            "storage": {"db_path": str(tmp_path / "auto.db"), "retention_days": 30},
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return str(config_file)


class TestAutomationIntegration:
    """Integration tests for automation module."""

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    @patch("hp_ctl.automation.controller.WeatherAPIClient")
    def test_automation_init_and_discovery(
        self, mock_weather_class, mock_uart, mock_mqtt_class, automation_config
    ):
        """Test that automation initializes and publishes discovery."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt

        # Ensure weather client doesn't return mocks that break math
        mock_weather = MagicMock()
        mock_weather_class.return_value = mock_weather
        mock_weather.get_last_data.return_value = None

        app = Application(config_path=automation_config)
        app.mqtt_client = mock_mqtt

        from hp_ctl.automation import AutomationController

        app.automation_controller = AutomationController(
            config=app.config["automation"],
            mqtt_client=app.mqtt_client,
            ha_mapper=app.ha_mapper,
        )
        app.automation_controller.start()

        # Check discovery calls for automation
        discovery_calls = [
            call
            for call in mock_mqtt.publish.call_args_list
            if "homeassistant/sensor/aquarea_k_automation" in str(call)
            or "homeassistant/select/aquarea_k_automation" in str(call)
        ]

        # We expect 10 entities
        assert len(discovery_calls) == 10

        # Check specific entity
        mode_discovery = [c for c in discovery_calls if "mode/config" in str(c)]
        assert len(mode_discovery) == 1
        # Payload is second arg, check it contains the topics
        payload = mode_discovery[0][0][1]
        assert payload["state_topic"] == "hp_ctl/aquarea_k/automation/mode"

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    @patch("hp_ctl.automation.controller.WeatherAPIClient")
    def test_automation_sensor_publishing(
        self, mock_weather_class, mock_uart, mock_mqtt_class, automation_config
    ):
        """Test that automation publishes individual sensor data."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt

        mock_weather = MagicMock()
        mock_weather_class.return_value = mock_weather
        mock_weather.get_last_data.return_value = None

        app = Application(config_path=automation_config)
        app.mqtt_client = mock_mqtt

        from hp_ctl.automation import AutomationController

        app.automation_controller = AutomationController(
            config=app.config["automation"],
            mqtt_client=app.mqtt_client,
            ha_mapper=app.ha_mapper,
        )

        # Simulate receiving outdoor temp from HP
        app.automation_controller._on_mqtt_state_message(
            "hp_ctl/aquarea_k/state/outdoor_temp", "7.5"
        )

        # Should publish to individual topic (controller passes relative topic to MqttClient)
        mock_mqtt.publish.assert_any_call("aquarea_k/automation/outdoor_temp_avg_24h", "7.5")

        # Should also publish to status JSON
        status_calls = [
            c for c in mock_mqtt.publish.call_args_list if "automation/status" in str(c)
        ]
        assert len(status_calls) > 0

    @patch("hp_ctl.main.MqttClient")
    @patch("hp_ctl.main.UartTransceiver")
    @patch("hp_ctl.automation.controller.WeatherAPIClient")
    def test_automation_mode_switching(
        self, mock_weather_class, mock_uart, mock_mqtt_class, automation_config
    ):
        """Test switching automation mode via MQTT."""
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt

        mock_weather = MagicMock()
        mock_weather_class.return_value = mock_weather
        mock_weather.get_last_data.return_value = None

        app = Application(config_path=automation_config)
        app.mqtt_client = mock_mqtt

        from hp_ctl.automation import AutomationController

        app.automation_controller = AutomationController(
            config=app.config["automation"],
            mqtt_client=app.mqtt_client,
            ha_mapper=app.ha_mapper,
        )

        # Initial mode should be True (based on config enabled: True)
        assert app.automation_controller.automatic_mode_enabled is True

        # Switch to manual
        app.automation_controller._on_automation_mode_command(
            "hp_ctl/aquarea_k/automation/mode/set", "manual"
        )

        assert app.automation_controller.automatic_mode_enabled is False
        mock_mqtt.publish.assert_any_call("aquarea_k/automation/mode", "manual")
