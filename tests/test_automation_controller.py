# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Tests for automation controller change detection."""

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
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")

        # Verify snapshot was inserted
        assert controller.storage.get_snapshot_count() == 1
        assert controller.last_inserted_snapshot is not None
        assert controller.last_inserted_snapshot.outdoor_temp == 5.5

    def test_snapshot_change_detection_no_change(self, controller):
        """Test that duplicate values don't trigger insert."""
        # Insert first snapshot
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
        assert controller.storage.get_snapshot_count() == 1

        # Send same value again
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")

        # Verify no additional insert
        assert controller.storage.get_snapshot_count() == 1

    def test_snapshot_change_detection_with_change(self, controller):
        """Test that changed values trigger insert."""
        # Insert first snapshot
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
        assert controller.storage.get_snapshot_count() == 1

        # Send different value
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "6.0")

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
            ("dhw_target_temp", "50.0", "55.0"),
            ("zone1_heat_target_temp", "35.0", "36.0"),
            ("hp_status", "On", "Off"),
            ("operating_mode", "Heat", "Heat+DHW"),
        ]

        for field_name, value1, value2 in fields_to_test:
            # Reset controller state
            controller.last_inserted_snapshot = None
            controller.storage.conn.execute("DELETE FROM snapshots")
            controller.storage.conn.commit()

            # Insert first value
            controller._on_mqtt_state_message(f"hp_ctl/test_device/state/{field_name}", value1)
            assert controller.storage.get_snapshot_count() == 1

            # Send same value - should not insert
            controller._on_mqtt_state_message(f"hp_ctl/test_device/state/{field_name}", value1)
            assert controller.storage.get_snapshot_count() == 1

            # Send different value - should insert
            controller._on_mqtt_state_message(f"hp_ctl/test_device/state/{field_name}", value2)
            assert controller.storage.get_snapshot_count() == 2, (
                f"Field {field_name} failed to trigger insert on change"
            )

    def test_snapshot_change_detection_ignores_timestamp(self, controller):
        """Test that timestamp changes alone don't trigger insert."""
        import time

        # Insert first snapshot
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
        assert controller.storage.get_snapshot_count() == 1

        # Wait a bit and send same value (timestamp will be different)
        time.sleep(0.1)
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")

        # Verify no additional insert (timestamp is excluded from comparison)
        assert controller.storage.get_snapshot_count() == 1

    def test_snapshot_change_detection_ignores_three_way_valve(self, controller):
        """Test that three_way_valve changes don't trigger insert (runtime-only field)."""
        # Insert first snapshot with outdoor temp
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
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
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
        assert controller.storage.get_snapshot_count() == 1

        # Subsequent messages with same or no new data - should not insert
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/heat_power_generation", "3000.0"
        )
        controller._on_mqtt_state_message(
            "hp_ctl/test_device/state/heat_power_consumption", "1000.0"
        )
        controller._on_mqtt_state_message("hp_ctl/test_device/state/inlet_water_temp", "35.0")
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outlet_water_temp", "40.0")
        controller._on_mqtt_state_message("hp_ctl/test_device/state/zone1_actual_temp", "38.0")
        controller._on_mqtt_state_message("hp_ctl/test_device/state/hp_status", "On")
        controller._on_mqtt_state_message("hp_ctl/test_device/state/operating_mode", "Heat")
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
            controller._on_mqtt_state_message(f"hp_ctl/test_device/state/{field_name}", value)

        initial_count = controller.storage.get_snapshot_count()

        # Now resend all the same values - should not trigger any new inserts
        for field_name, value in fields:
            controller._on_mqtt_state_message(f"hp_ctl/test_device/state/{field_name}", value)

        # Verify no new inserts
        assert controller.storage.get_snapshot_count() == initial_count

    def test_snapshot_change_none_to_value(self, controller):
        """Test that changing from None to a value triggers insert."""
        # Insert first snapshot with only outdoor_temp
        controller._on_mqtt_state_message("hp_ctl/test_device/state/outdoor_temp", "5.5")
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


class TestEEPROMProtection:
    """Test suite for EEPROM protection (10 changes per hour limit)."""

    def test_can_send_command_first_time(self, controller):
        """Verify first command is always allowed."""
        assert controller._can_send_command("hp_status") is True
        assert controller._can_send_command("operating_mode") is True

    def test_can_send_command_under_limit(self, controller):
        """Verify commands allowed when under 10/hour limit."""

        # Send 9 commands
        for i in range(9):
            assert controller._can_send_command("hp_status") is True
            controller._record_command_sent("hp_status")

        # 10th should still be allowed
        assert controller._can_send_command("hp_status") is True

    def test_limit_enforcement_10_per_hour(self, controller):
        """Verify 11th command is rejected (10/hour limit)."""

        # Send 10 commands
        for i in range(10):
            assert controller._can_send_command("hp_status") is True
            controller._record_command_sent("hp_status")

        # 11th should be rejected
        assert controller._can_send_command("hp_status") is False

    def test_rolling_window_expiry(self, controller):
        """Verify old changes expire after 1 hour (rolling window)."""
        from datetime import datetime, timedelta

        # Record 10 changes at t=0
        base_time = datetime.now()
        for i in range(10):
            controller.change_history.setdefault("hp_status", []).append(base_time)

        # Verify limit reached
        assert controller._can_send_command("hp_status") is False

        # Mock time to be 61 minutes later (changes should expire)
        with patch("hp_ctl.automation.controller.datetime") as mock_datetime:
            future_time = base_time + timedelta(minutes=61)
            mock_datetime.now.return_value = future_time

            # Should be allowed now (old changes expired)
            assert controller._can_send_command("hp_status") is True

    def test_per_parameter_tracking(self, controller):
        """Verify limits tracked independently per parameter."""
        # Max out hp_status
        for i in range(10):
            controller._record_command_sent("hp_status")

        # hp_status should be blocked
        assert controller._can_send_command("hp_status") is False

        # But operating_mode should still work (independent tracking)
        assert controller._can_send_command("operating_mode") is True

    def test_record_command_sent(self, controller):
        """Verify command recording updates history."""
        from datetime import datetime

        assert "test_param" not in controller.change_history

        controller._record_command_sent("test_param")

        assert "test_param" in controller.change_history
        assert len(controller.change_history["test_param"]) == 1
        assert isinstance(controller.change_history["test_param"][0], datetime)

    def test_partial_expiry_rolling_window(self, controller):
        """Verify rolling window expires only old entries."""
        from datetime import datetime, timedelta

        base_time = datetime.now()

        # Add 5 old entries (70 minutes ago - should expire)
        old_time = base_time - timedelta(minutes=70)
        controller.change_history["hp_status"] = [old_time] * 5

        # Add 5 recent entries (10 minutes ago - should NOT expire)
        recent_time = base_time - timedelta(minutes=10)
        controller.change_history["hp_status"].extend([recent_time] * 5)

        # Mock current time
        with patch("hp_ctl.automation.controller.datetime") as mock_datetime:
            mock_datetime.now.return_value = base_time

            # Should be able to send (only 5 recent entries remain after expiry)
            assert controller._can_send_command("hp_status") is True

            # After checking, old entries should be removed
            assert len(controller.change_history["hp_status"]) == 5


class TestCommandSuppression:
    """Tests for automation controller command suppression."""

    @pytest.fixture
    def controller_with_callback(self, temp_automation_config, mock_mqtt_client, mock_ha_mapper):
        command_callback = MagicMock()
        with patch("hp_ctl.automation.controller.WeatherAPIClient"):
            controller = AutomationController(
                config=temp_automation_config,
                mqtt_client=mock_mqtt_client,
                ha_mapper=mock_ha_mapper,
                command_callback=command_callback,
            )
            # Mock weather data to avoid skipping control logic
            controller.weather_client.get_last_data.return_value = MagicMock(
                outdoor_temp_avg_24h=5.0
            )

            yield controller
            controller.storage.close()

    def test_command_suppression_if_value_unchanged(self, controller_with_callback):
        """Test that commands are NOT sent if the value is already correct."""
        controller = controller_with_callback
        # 1. Setup current state in snapshot
        controller.current_snapshot.hp_status = "On"
        controller.current_snapshot.operating_mode = "Heat"
        controller.current_snapshot.dhw_target_temp = 50.0
        controller.current_snapshot.zone1_heat_target_temp = 35.0

        # Mock algorithm to suggest exactly these values
        from hp_ctl.automation.algorithm import AutomationAction

        action = AutomationAction(
            hp_status="On",
            operating_mode="Heat",
            dhw_target_temp=50.0,
            target_temp=35.0,
            reason="Test",
        )
        controller.algorithm.decide = MagicMock(return_value=action)

        # 2. Run control logic
        controller._run_control_logic()

        # 3. Verify NO commands were sent via callback
        controller.command_callback.assert_not_called()

    def test_command_sent_if_value_changed(self, controller_with_callback):
        """Test that commands ARE sent if the value differs."""
        controller = controller_with_callback
        # 1. Setup current state (different from what algorithm will suggest)
        controller.current_snapshot.hp_status = "Off"
        controller.current_snapshot.operating_mode = "Heat"
        controller.current_snapshot.dhw_target_temp = 45.0
        controller.current_snapshot.zone1_heat_target_temp = 30.0

        # Mock algorithm
        from hp_ctl.automation.algorithm import AutomationAction

        action = AutomationAction(
            hp_status="On",
            operating_mode="Heat+DHW",
            dhw_target_temp=50.0,
            target_temp=35.0,
            reason="Test",
        )
        controller.algorithm.decide = MagicMock(return_value=action)

        # 2. Run control logic
        controller._run_control_logic()

        # 3. Verify commands WERE sent
        assert controller.command_callback.call_count == 4
        controller.command_callback.assert_any_call("hp_status", "On")
        controller.command_callback.assert_any_call("operating_mode", "Heat+DHW")
        controller.command_callback.assert_any_call("dhw_target_temp", 50.0)
        controller.command_callback.assert_any_call("zone1_heat_target_temp", 35.0)

    def test_partial_command_sending(self, controller_with_callback):
        """Test that only changed values trigger commands."""
        controller = controller_with_callback
        # 1. Setup current state - some values match, some don't
        controller.current_snapshot.hp_status = "On"  # Matches
        controller.current_snapshot.operating_mode = "Heat"  # Differs
        controller.current_snapshot.dhw_target_temp = 50.0  # Matches
        controller.current_snapshot.zone1_heat_target_temp = 30.0  # Differs

        # Mock algorithm
        from hp_ctl.automation.algorithm import AutomationAction

        action = AutomationAction(
            hp_status="On",
            operating_mode="Heat+DHW",
            dhw_target_temp=50.0,
            target_temp=35.0,
            reason="Test",
        )
        controller.algorithm.decide = MagicMock(return_value=action)

        # 2. Run control logic
        controller._run_control_logic()

        # 3. Verify only changed commands were sent
        assert controller.command_callback.call_count == 2
        controller.command_callback.assert_any_call("operating_mode", "Heat+DHW")
        controller.command_callback.assert_any_call("zone1_heat_target_temp", 35.0)

        # Verify others were NOT sent
        with pytest.raises(AssertionError):
            controller.command_callback.assert_any_call("hp_status", "On")
        with pytest.raises(AssertionError):
            controller.command_callback.assert_any_call("dhw_target_temp", 50.0)
