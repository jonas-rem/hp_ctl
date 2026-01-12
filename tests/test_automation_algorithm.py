# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

from datetime import datetime

import pytest

from hp_ctl.automation.algorithm import HeatingAlgorithm


@pytest.fixture
def algorithm():
    config = {
        "night_off_period": {"start": "22:00", "end": "06:00"},
        "ramping": {"min_delta_t": 3.0},
        "dhw": {"enabled": True, "start_time": "13:00", "target_temp": 50.0},
        "heat_demand_map": [
            {"outdoor_temp": -10, "daily_kwh": 75},
            {"outdoor_temp": 20, "daily_kwh": 0},
        ],
    }
    return HeatingAlgorithm(config)


def test_night_off_detection(algorithm):
    # During night off
    t1 = datetime.strptime("23:00", "%H:%M")
    assert algorithm.is_in_night_off_period(t1) is True

    t2 = datetime.strptime("02:00", "%H:%M")
    assert algorithm.is_in_night_off_period(t2) is True

    # Day time
    t3 = datetime.strptime("12:00", "%H:%M")
    assert algorithm.is_in_night_off_period(t3) is False


def test_kwh_bucket_logic(algorithm):
    now = datetime.strptime("12:00", "%H:%M")

    # Demand met
    action = algorithm.decide(
        current_time=now,
        outdoor_temp_forecast_24h=5.0,
        actual_heat_kwh_today=35.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=33.0,
        current_hp_status="On",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=5000.0,
        heat_power_consumption=1000.0,
    )
    assert action.hp_status == "Off"
    assert "demand met" in action.reason.lower()


def test_ramping_logic_low_delta(algorithm):
    """Test target increase when delta_t is low."""
    now = datetime.strptime("12:00", "%H:%M")

    # delta_t = 35 - 33 = 2.0 (<= min_delta_t 3.0)
    action = algorithm.decide(
        current_time=now,
        outdoor_temp_forecast_24h=5.0,
        actual_heat_kwh_today=10.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=33.0,
        zone1_actual_temp=34.0,
        current_hp_status="On",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=3000.0,
        heat_power_consumption=800.0,
    )
    assert action.hp_status == "On"
    assert action.target_temp == 35.0  # zone1_actual_temp (34.0) + 1.0


def test_ramping_logic_high_delta(algorithm):
    """Test target maintenance when delta_t is high."""
    now = datetime.strptime("12:00", "%H:%M")

    # delta_t = 35 - 30 = 5.0 (> min_delta_t 3.0)
    action = algorithm.decide(
        current_time=now,
        outdoor_temp_forecast_24h=5.0,
        actual_heat_kwh_today=10.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=34.5,
        current_hp_status="On",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=3000.0,
        heat_power_consumption=800.0,
    )
    assert action.hp_status == "On"
    assert action.target_temp == 34.5  # matches zone1_actual_temp


def test_dhw_trigger_window(algorithm):
    """Test DHW trigger during its window."""
    now = datetime.strptime("13:05", "%H:%M")

    action = algorithm.decide(
        current_time=now,
        outdoor_temp_forecast_24h=5.0,
        actual_heat_kwh_today=10.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=34.5,
        current_hp_status="On",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=3000.0,
        heat_power_consumption=800.0,
    )
    assert action.operating_mode == "Heat+DHW"
    assert action.dhw_target_temp == 50.0
    assert "DHW trigger window" in action.reason


def test_dhw_completion(algorithm):
    """Test switching back to Heat once DHW is done."""
    now = datetime.strptime("14:30", "%H:%M")  # Past 1-hour trigger window

    action = algorithm.decide(
        current_time=now,
        outdoor_temp_forecast_24h=5.0,
        actual_heat_kwh_today=10.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=34.5,
        current_hp_status="On",
        current_operating_mode="Heat+DHW",
        three_way_valve="Room",  # Valve switched back!
        heat_power_generation=3000.0,
        heat_power_consumption=800.0,
    )
    assert action.operating_mode == "Heat"
    assert "DHW finished" in action.reason


# --- Tests for dynamic heating start time ---


@pytest.fixture
def algorithm_with_night_off():
    """Algorithm with night_off_period ending at 07:30 and DHW at 13:00."""
    config = {
        "night_off_period": {"start": "22:30", "end": "07:30"},
        "ramping": {"min_delta_t": 3.0},
        "dhw": {"enabled": True, "start_time": "13:00", "target_temp": 50.0},
        "heat_demand_map": [
            {"outdoor_temp": -10, "daily_kwh": 75},
            {"outdoor_temp": 20, "daily_kwh": 0},
        ],
    }
    return HeatingAlgorithm(config)


def test_calculate_heating_start_time_cold_day(algorithm_with_night_off):
    """Cold day (<=0C) starts at earliest time (night_off end)."""
    # At 0C or below, should return earliest start time (07:30)
    start_time, reason = algorithm_with_night_off.calculate_heating_start_time(-5.0)
    assert start_time == "07:30"
    assert "cold day" in reason

    start_time, reason = algorithm_with_night_off.calculate_heating_start_time(0.0)
    assert start_time == "07:30"
    assert "cold day" in reason


def test_calculate_heating_start_time_warm_day(algorithm_with_night_off):
    """Warm day (>=17C) starts at latest time (DHW start)."""
    # Warm threshold = 20 - 3 = 17C
    start_time, reason = algorithm_with_night_off.calculate_heating_start_time(17.0)
    assert start_time == "13:00"
    assert "warm day" in reason

    start_time, reason = algorithm_with_night_off.calculate_heating_start_time(20.0)
    assert start_time == "13:00"
    assert "warm day" in reason


def test_calculate_heating_start_time_interpolation(algorithm_with_night_off):
    """Mid-range temp interpolates between earliest and latest."""
    # Range: 0C to 17C maps to 07:30 (450 min) to 13:00 (780 min)
    # Total time range: 330 minutes
    # At 8.5C (midpoint of 0-17): should be approximately 09:39

    start_time, reason = algorithm_with_night_off.calculate_heating_start_time(8.5)
    assert "interpolated" in reason

    assert start_time == "09:06"


def test_calculate_heating_start_time_no_dhw():
    """When DHW disabled, uses default latest start time of 13:00."""
    config = {
        "night_off_period": {"start": "22:30", "end": "07:30"},
        "dhw": {"enabled": False},
        "heat_demand_map": [
            {"outdoor_temp": -10, "daily_kwh": 75},
            {"outdoor_temp": 20, "daily_kwh": 0},
        ],
    }
    algo = HeatingAlgorithm(config)

    # Warm day should still use 13:00 as latest
    start_time, _ = algo.calculate_heating_start_time(18.0)
    assert start_time == "13:00"


def test_is_before_heating_start_in_delayed_window(algorithm_with_night_off):
    """HP should stay off during delayed start window."""
    # Night off ends at 07:30, calculated start is 10:00
    # At 08:00, we're in the delayed window
    assert algorithm_with_night_off.is_before_heating_start(
        datetime.strptime("08:00", "%H:%M"), "10:00"
    )

    # At 09:59, still in delayed window
    assert algorithm_with_night_off.is_before_heating_start(
        datetime.strptime("09:59", "%H:%M"), "10:00"
    )


def test_is_before_heating_start_past_start_time(algorithm_with_night_off):
    """HP follows normal logic after calculated start time."""
    # At 10:00 or later, not in delayed window
    assert not algorithm_with_night_off.is_before_heating_start(
        datetime.strptime("10:00", "%H:%M"), "10:00"
    )

    assert not algorithm_with_night_off.is_before_heating_start(
        datetime.strptime("11:00", "%H:%M"), "10:00"
    )


def test_is_before_heating_start_before_night_off_end(algorithm_with_night_off):
    """Before night_off ends, is_before_heating_start should return False.

    The night_off check handles this case separately.
    """
    # At 06:00, still in night off (before 07:30 end)
    # This should return False because night_off check handles it
    assert not algorithm_with_night_off.is_before_heating_start(
        datetime.strptime("06:00", "%H:%M"), "10:00"
    )


def test_decide_delayed_start(algorithm_with_night_off):
    """Integration: decide() returns Off with delayed start reason."""
    # Warm day (10C) -> calculated start around 09:27
    # At 08:00, should be delayed
    now = datetime.strptime("08:00", "%H:%M")

    action = algorithm_with_night_off.decide(
        current_time=now,
        outdoor_temp_forecast_24h=10.0,  # Warm enough for delayed start
        actual_heat_kwh_today=0.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=33.0,
        current_hp_status="Off",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=0.0,
        heat_power_consumption=0.0,
    )
    assert action.hp_status == "Off"
    assert "Delayed start until" in action.reason


def test_decide_past_delayed_start(algorithm_with_night_off):
    """After delayed start time, HP follows normal heating logic."""
    # At 10C, calculated start is 10:44 (based on 0-17C range mapping to 07:30-13:00)
    # At 11:00, should follow normal logic (heating)
    now = datetime.strptime("11:00", "%H:%M")

    action = algorithm_with_night_off.decide(
        current_time=now,
        outdoor_temp_forecast_24h=10.0,
        actual_heat_kwh_today=0.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=33.0,
        current_hp_status="Off",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=0.0,
        heat_power_consumption=0.0,
    )
    # Should be heating, not delayed
    assert action.hp_status == "On"
    assert "Heating" in action.reason


def test_decide_cold_day_no_delay(algorithm_with_night_off):
    """On cold days, HP starts immediately after night_off ends."""
    # Cold day (-5C) -> calculated start is 07:30 (earliest)
    # At 07:31, should start heating immediately
    now = datetime.strptime("07:31", "%H:%M")

    action = algorithm_with_night_off.decide(
        current_time=now,
        outdoor_temp_forecast_24h=-5.0,  # Cold day
        actual_heat_kwh_today=0.0,
        estimated_demand_kwh=50.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=33.0,
        current_hp_status="Off",
        current_operating_mode="Heat",
        three_way_valve="Room",
        heat_power_generation=0.0,
        heat_power_consumption=0.0,
    )
    assert action.hp_status == "On"
    assert "Heating" in action.reason
