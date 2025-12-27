# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

from datetime import datetime

import pytest

from hp_ctl.automation.algorithm import HeatingAlgorithm


@pytest.fixture
def algorithm():
    config = {
        "night_off_periods": [{"start": "22:00", "end": "06:00"}],
        "ramping": {"min_delta_t": 3.0},
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
        outdoor_temp_avg_24h=5.0,
        actual_heat_kwh_today=35.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=33.0,
        current_hp_status="On",
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
        outdoor_temp_avg_24h=5.0,
        actual_heat_kwh_today=10.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=33.0,
        zone1_actual_temp=34.0,
        current_hp_status="On",
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
        outdoor_temp_avg_24h=5.0,
        actual_heat_kwh_today=10.0,
        estimated_demand_kwh=30.0,
        current_outlet_temp=35.0,
        current_inlet_temp=30.0,
        zone1_actual_temp=34.5,
        current_hp_status="On",
        heat_power_generation=3000.0,
        heat_power_consumption=800.0,
    )
    assert action.hp_status == "On"
    assert action.target_temp == 34.5  # matches zone1_actual_temp
