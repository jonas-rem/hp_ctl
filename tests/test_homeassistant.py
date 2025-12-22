# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import pytest

from hp_ctl.homeassistant import HomeAssistantMapper
from hp_ctl.protocol import EXTRA_FIELDS, STANDARD_FIELDS, Message


@pytest.fixture
def mapper():
    """Create a HomeAssistantMapper instance for testing."""
    return HomeAssistantMapper(device_id="test_aquarea", device_name="Test Aquarea")


def test_discovery_config_structure(mapper):
    """Test that discovery config has required Home Assistant fields."""
    all_fields = STANDARD_FIELDS + EXTRA_FIELDS
    configs = mapper.message_to_ha_discovery(all_fields)

    assert len(configs) == len(all_fields)

    for topic, config in configs.items():
        assert topic.startswith("homeassistant/sensor/test_aquarea/")
        assert "name" in config
        assert "state_topic" in config
        assert "unique_id" in config
        assert "device" in config


def test_discovery_uses_field_metadata(mapper):
    """Test that discovery config uses FieldSpec metadata."""
    all_fields = STANDARD_FIELDS + EXTRA_FIELDS
    configs = mapper.message_to_ha_discovery(all_fields)

    # Find temperature field
    temp_field = next(f for f in STANDARD_FIELDS if f.name == "zone1_actual_temp")
    temp_config = next(c for c in configs.values() if "zone1_actual_temp" in c["unique_id"])

    assert temp_config["unit_of_measurement"] == temp_field.unit
    assert temp_config["device_class"] == temp_field.ha_class
    assert temp_config["state_class"] == temp_field.ha_state_class
    assert temp_config["icon"] == temp_field.ha_icon


def test_state_updates_from_message(mapper):
    """Test state updates generation from decoded message."""
    message = Message(
        packet_type=0x10,
        fields={
            "quiet_mode": "Off",
            "zone1_actual_temp": 48,
            "heat_power_consumption": 0.0,
        },
    )

    updates = mapper.message_to_state_updates(message)

    assert updates["test_aquarea/state/quiet_mode"] == "Off"
    assert updates["test_aquarea/state/zone1_actual_temp"] == "48"
    assert updates["test_aquarea/state/heat_power_consumption"] == "0.0"


def test_default_device_config():
    """Test default device configuration."""
    mapper = HomeAssistantMapper()

    assert mapper.device_id == "aquarea_k"
    assert mapper.device_name == "Aquarea K"
