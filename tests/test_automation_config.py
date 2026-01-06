# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Tests for automation config validation."""

import pytest

from hp_ctl.automation.config import get_heat_demand_for_temp, validate_automation_config


def test_validate_minimal_config():
    """Test validation of minimal valid config."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "storage": {
            "db_path": "/tmp/test.db",
            "retention_days": 30,
        },
    }

    # Should not raise
    validate_automation_config(config)


def test_validate_disabled_config():
    """Test that 'enabled' field is optional (controller always runs)."""
    # Even with enabled=False, all sections are required since controller runs
    config = {
        "enabled": False,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "storage": {
            "db_path": "/tmp/test.db",
            "retention_days": 30,
        },
    }

    # Should not raise - enabled field just controls startup mode
    validate_automation_config(config)


def test_validate_missing_weather_section():
    """Test error on missing weather section."""
    config = {
        "enabled": True,
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "storage": {"db_path": "/tmp/test.db", "retention_days": 30},
    }

    with pytest.raises(ValueError, match="Missing required section: automation.weather"):
        validate_automation_config(config)


def test_validate_invalid_latitude():
    """Test error on invalid latitude."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 100.0,  # Invalid: > 90
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "storage": {"db_path": "/tmp/test.db", "retention_days": 30},
    }

    with pytest.raises(ValueError, match="Invalid latitude"):
        validate_automation_config(config)


def test_validate_heat_demand_map_too_few_entries():
    """Test error when heat demand map has < 2 entries."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            # Only 1 entry
        ],
        "storage": {"db_path": "/tmp/test.db", "retention_days": 30},
    }

    with pytest.raises(ValueError, match="at least 2 entries"):
        validate_automation_config(config)


def test_validate_heat_demand_map_not_ascending():
    """Test error when temps are not in ascending order."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 10, "daily_kwh": 20},
            {"outdoor_temp": 0, "daily_kwh": 35},  # Out of order
        ],
        "storage": {"db_path": "/tmp/test.db", "retention_days": 30},
    }

    with pytest.raises(ValueError, match="ascending order"):
        validate_automation_config(config)


def test_get_heat_demand_exact_match():
    """Test heat demand calculation for exact match."""
    heat_demand_map = [
        {"outdoor_temp": 0, "daily_kwh": 35},
        {"outdoor_temp": 10, "daily_kwh": 20},
    ]

    assert get_heat_demand_for_temp(heat_demand_map, 0) == 35
    assert get_heat_demand_for_temp(heat_demand_map, 10) == 20


def test_get_heat_demand_interpolation():
    """Test heat demand calculation with linear interpolation."""
    heat_demand_map = [
        {"outdoor_temp": 0, "daily_kwh": 30},
        {"outdoor_temp": 10, "daily_kwh": 20},
    ]

    # Midpoint: should be 25 kWh
    result = get_heat_demand_for_temp(heat_demand_map, 5)
    assert result == 25.0

    # 1/4 of the way: 30 - (10 * 0.25) = 27.5
    result = get_heat_demand_for_temp(heat_demand_map, 2.5)
    assert result == 27.5


def test_get_heat_demand_below_range():
    """Test heat demand for temp below lowest mapping."""
    heat_demand_map = [
        {"outdoor_temp": 0, "daily_kwh": 35},
        {"outdoor_temp": 10, "daily_kwh": 20},
    ]

    # Below range: should return lowest value
    result = get_heat_demand_for_temp(heat_demand_map, -10)
    assert result == 35


def test_get_heat_demand_above_range():
    """Test heat demand for temp above highest mapping."""
    heat_demand_map: list[dict[str, float]] = [
        {"outdoor_temp": 0.0, "daily_kwh": 35.0},
        {"outdoor_temp": 10.0, "daily_kwh": 20.0},
    ]

    # Above range: should return highest value
    result = get_heat_demand_for_temp(heat_demand_map, 20)
    assert result == 20


def test_validate_night_off_period():
    """Test validation of night_off_period (singular)."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "night_off_period": {
            "start": "22:30",
            "end": "07:30",
        },
        "storage": {
            "db_path": "/tmp/test.db",
            "retention_days": 30,
        },
    }

    # Should not raise
    validate_automation_config(config)


def test_validate_night_off_period_invalid_format():
    """Test error on invalid time format in night_off_period."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "night_off_period": {
            "start": "25:00",  # Invalid hour
            "end": "07:30",
        },
        "storage": {
            "db_path": "/tmp/test.db",
            "retention_days": 30,
        },
    }

    with pytest.raises(ValueError, match="Invalid time format in night_off_period.start"):
        validate_automation_config(config)


def test_validate_night_off_period_missing_fields():
    """Test error when night_off_period is missing start or end."""
    config = {
        "enabled": True,
        "weather": {
            "latitude": 52.52,
            "longitude": 13.41,
        },
        "heat_demand_map": [
            {"outdoor_temp": 0, "daily_kwh": 35},
            {"outdoor_temp": 10, "daily_kwh": 20},
        ],
        "night_off_period": {
            "start": "22:30",
            # Missing 'end'
        },
        "storage": {
            "db_path": "/tmp/test.db",
            "retention_days": 30,
        },
    }

    with pytest.raises(ValueError, match="night_off_period must have 'start' and 'end'"):
        validate_automation_config(config)
