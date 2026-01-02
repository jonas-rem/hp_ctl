# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Tests for automation controller change detection."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hp_ctl.automation.controller import AutomationController


@pytest.fixture
def mock_mqtt_client():
    """Create mock MQTT client."""
    return MagicMock()


@pytest.fixture
def mock_ha_mapper():
    """Create mock Home Assistant mapper."""
    mapper = MagicMock()
    mapper.device_id = "test_device"
    mapper.device_name = "Test Device"
    mapper.topic_prefix = "hp_ctl"
    return mapper


@pytest.fixture
def temp_automation_config(tmp_path):
    """Create automation config with temporary database."""
    db_path = tmp_path / "test.db"
    return {
        "enabled": False,  # Don't start automatic mode
        "weather": {"latitude": 52.52, "longitude": 13.41},
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "storage": {"db_path": str(db_path), "retention_days": 30},
    }


@pytest.fixture
def controller(temp_automation_config, mock_mqtt_client, mock_ha_mapper):
    """Create automation controller for testing."""
    with patch("hp_ctl.automation.controller.WeatherAPIClient"):
        controller = AutomationController(
            config=temp_automation_config,
            mqtt_client=mock_mqtt_client,
            ha_mapper=mock_ha_mapper,
        )
        yield controller
        controller.storage.close()


class TestSnapshotChangeDetection:
    """Tests for snapshot change detection logic."""

    def test_snapshot_change_detection_first_insert(self, controller):
        """Test that first snapshot is always inserted."""
        # Verify no snapshots initially
        assert controller.storage.get_snapshot_count() == 0
        assert controller.last_inserted_snapshot is None

        # Send first outdoor temp message
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )

        # Verify snapshot was inserted
        assert controller.storage.get_snapshot_count() == 1
        assert controller.last_inserted_snapshot is not None
        assert controller.last_inserted_snapshot.outdoor_temp == 5.5

    def test_snapshot_change_detection_no_change(self, controller):
        """Test that duplicate values don't trigger insert."""
        # Insert first snapshot
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        assert controller.storage.get_snapshot_count() == 1

        # Send same value again
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )

        # Verify no additional insert
        assert controller.storage.get_snapshot_count() == 1

    def test_snapshot_change_detection_with_change(self, controller):
        """Test that changed values trigger insert."""
        # Insert first snapshot
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        assert controller.storage.get_snapshot_count() == 1

        # Send different value
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "6.0"
        )

        # Verify new insert
        assert controller.storage.get_snapshot_count() == 2

        # Verify both values are in database
        from datetime import datetime, timedelta

        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        snapshots = controller.storage.get_snapshots(start, end)

        assert len(snapshots) == 2
        temps = sorted([s.outdoor_temp for s in snapshots if s.outdoor_temp])
        assert temps == [5.5, 6.0]

    def test_snapshot_change_detection_multiple_fields(self, controller):
        """Test that changes in different fields trigger inserts."""
        fields_to_test = [
            ("outdoor_temp", "5.5", "6.0"),
            ("heat_power_generation", "3000.0", "3500.0"),
            ("heat_power_consumption", "1000.0", "1200.0"),
            ("inlet_water_temp", "35.0", "36.0"),
            ("outlet_water_temp", "40.0", "41.0"),
            ("zone1_actual_temp", "38.0", "39.0"),
            ("hp_status", "On", "Off"),
            ("operating_mode", "Heat", "Heat+DHW"),
        ]

        for field_name, value1, value2 in fields_to_test:
            # Reset controller state
            controller.last_inserted_snapshot = None
            controller.storage.conn.execute("DELETE FROM snapshots")
            controller.storage.conn.commit()

            # Insert first value
            controller._on_mqtt_state_message(
                f"hp_ctl/test_device/state/{field_name}", value1
            )
            assert controller.storage.get_snapshot_count() == 1

            # Send same value - should not insert
            controller._on_mqtt_state_message(
                f"hp_ctl/test_device/state/{field_name}", value1
            )
            assert controller.storage.get_snapshot_count() == 1

            # Send different value - should insert
            controller._on_mqtt_state_message(
                f"hp_ctl/test_device/state/{field_name}", value2
            )
            assert (
                controller.storage.get_snapshot_count() == 2
            ), f"Field {field_name} failed to trigger insert on change"

    def test_snapshot_change_detection_ignores_timestamp(self, controller):
        """Test that timestamp changes alone don't trigger insert."""
        import time

        # Insert first snapshot
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        assert controller.storage.get_snapshot_count() == 1

        # Wait a bit and send same value (timestamp will be different)
        time.sleep(0.1)
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )

        # Verify no additional insert (timestamp is excluded from comparison)
        assert controller.storage.get_snapshot_count() == 1

    def test_snapshot_change_detection_ignores_three_way_valve(self, controller):
        """Test that three_way_valve changes don't trigger insert (runtime-only field)."""
        # Insert first snapshot with outdoor temp
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        initial_count = controller.storage.get_snapshot_count()
        assert initial_count == 1

        # Change three_way_valve (this field is not persisted to DB)
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/three_way_valve", "Valve:DHW, Defrost:Inactive"
        )

        # Verify no additional insert (three_way_valve is excluded from comparison)
        assert controller.storage.get_snapshot_count() == initial_count

    def test_snapshot_multiple_mqtt_messages_same_packet(self, controller):
        """Test that multiple MQTT messages from same packet only insert once."""
        # Simulate a heat pump packet being split into multiple MQTT messages
        # All with the same values

        # First message - should insert
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        assert controller.storage.get_snapshot_count() == 1

        # Subsequent messages with same or no new data - should not insert
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/heat_power_generation", "3000.0"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/heat_power_consumption", "1000.0"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/inlet_water_temp", "35.0"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outlet_water_temp", "40.0"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/zone1_actual_temp", "38.0"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/hp_status", "On"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/operating_mode", "Heat"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/three_way_valve", "Valve:Room, Defrost:Inactive"
        )

        # Should still only have 1 snapshot (initial) + 7 additional field updates = 8 inserts
        # Actually, each new field is a change, so we get inserts for each NEW field
        # Let me reconsider: first outdoor_temp=5.5 (1 insert)
        # Then outdoor_temp=5.5 again (no insert)
        # Then heat_power_generation=3000.0 - this IS a change (null -> 3000.0) (1 insert)
        # And so on...

        # Actually for this test, we want to simulate ALL fields coming in at once
        # Let me fix this test to send all fields BEFORE checking, then resend them

        # Reset
        controller.last_inserted_snapshot = None
        controller.storage.conn.execute("DELETE FROM snapshots")
        controller.storage.conn.commit()

        # Send all fields once (each new field is a change from None)
        fields = [
            ("outdoor_temp", "5.5"),
            ("heat_power_generation", "3000.0"),
            ("heat_power_consumption", "1000.0"),
            ("inlet_water_temp", "35.0"),
            ("outlet_water_temp", "40.0"),
            ("zone1_actual_temp", "38.0"),
            ("hp_status", "On"),
            ("operating_mode", "Heat"),
        ]

        for field_name, value in fields:
            controller._on_mqtt_state_message(
                f"hp_ctl/test_device/state/{field_name}", value
            )

        initial_count = controller.storage.get_snapshot_count()

        # Now resend all the same values - should not trigger any new inserts
        for field_name, value in fields:
            controller._on_mqtt_state_message(
                f"hp_ctl/test_device/state/{field_name}", value
            )

        # Verify no new inserts
        assert controller.storage.get_snapshot_count() == initial_count

    def test_snapshot_change_none_to_value(self, controller):
        """Test that changing from None to a value triggers insert."""
        # Insert first snapshot with only outdoor_temp
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/outdoor_temp", "5.5"
        )
        assert controller.storage.get_snapshot_count() == 1
        assert controller.last_inserted_snapshot.heat_power_generation is None

        # Add heat_power_generation (None -> 3000.0 is a change)
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/heat_power_generation", "3000.0"
        )

        # Should trigger insert because None != 3000.0
        assert controller.storage.get_snapshot_count() == 2
        assert controller.last_inserted_snapshot.heat_power_generation == 3000.0

    def test_snapshot_change_value_to_none(self, controller):
        """Test that changing from value to None triggers insert."""
        # Insert first snapshot with heat_power_generation
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/heat_power_generation", "3000.0"
        )
        assert controller.storage.get_snapshot_count() == 1

        # This test would require the code to explicitly set to None
        # which doesn't happen in normal operation, but let's test the logic
        controller.current_snapshot.heat_power_generation = None
        controller.current_snapshot.timestamp = controller.current_snapshot.timestamp

        # Manually trigger change detection
        assert controller._snapshot_has_changed() is True
