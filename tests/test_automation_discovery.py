# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Tests for Home Assistant discovery of automation entities."""

from hp_ctl.automation.discovery import AutomationDiscovery


def test_automation_discovery_structure():
    """Test the structure of automation discovery configs."""
    discovery = AutomationDiscovery(device_id="test_hp", device_name="Test HP")
    configs = discovery.get_discovery_configs()

    # Should have 11 entities (1 select + 10 sensors including heating_start_time)
    assert len(configs) == 11

    # Check Mode Select
    mode_topic = "homeassistant/select/test_hp_automation/mode/config"
    assert mode_topic in configs
    mode_config = configs[mode_topic]
    assert mode_config["name"] == "Mode"
    assert mode_config["state_topic"] == "hp_ctl/test_hp/automation/mode"
    assert mode_config["command_topic"] == "hp_ctl/test_hp/automation/mode/set"
    assert mode_config["options"] == ["manual", "automatic"]
    assert mode_config["device"]["identifiers"] == ["test_hp_automation"]
    assert mode_config["device"]["via_device"] == "test_hp"

    # Check Outdoor Temp Sensor
    temp_topic = "homeassistant/sensor/test_hp_automation/outdoor_temp_forecast_24h/config"
    assert temp_topic in configs
    temp_config = configs[temp_topic]
    assert temp_config["name"] == "Outdoor Temperature (24h Forecast)"
    assert temp_config["unit_of_measurement"] == "°C"
    assert temp_config["device_class"] == "temperature"
    assert temp_config["state_class"] == "measurement"

    # Check energy sensors
    energy_topic = "homeassistant/sensor/test_hp_automation/today_total_heat_kwh/config"
    assert energy_topic in configs
    energy_config = configs[energy_topic]
    assert energy_config["name"] == "Total Heat Energy Today"
    assert energy_config["unit_of_measurement"] == "kWh"
    assert energy_config["state_topic"] == "hp_ctl/test_hp/automation/today/total_heat_kwh"
    assert energy_config["state_class"] == "total_increasing"


def test_automation_discovery_unique_ids():
    """Test that all automation entities have unique IDs."""
    discovery = AutomationDiscovery(device_id="test_hp", device_name="Test HP")
    configs = discovery.get_discovery_configs()

    unique_ids = [config["unique_id"] for config in configs.values()]
    assert len(unique_ids) == len(set(unique_ids))
    for uid in unique_ids:
        assert uid.startswith("test_hp_automation_")
