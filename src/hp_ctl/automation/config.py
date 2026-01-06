# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Configuration validation for automation module."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate_automation_config(config: dict[str, Any]) -> None:
    """Validate automation configuration section.

    Note: Controller always runs for data collection. The 'enabled' field
    controls whether automatic heat pump control is active on startup.

    Args:
        config: Automation configuration dictionary.

    Raises:
        ValueError: If configuration is invalid.
    """
    # Validate weather section
    if "weather" not in config:
        raise ValueError("Missing required section: automation.weather")

    weather = config["weather"]
    required_weather_fields = ["latitude", "longitude"]
    for field in required_weather_fields:
        if field not in weather:
            raise ValueError(f"Missing required field: automation.weather.{field}")

    # Validate latitude/longitude ranges
    if not -90 <= weather["latitude"] <= 90:
        raise ValueError(f"Invalid latitude {weather['latitude']}: must be between -90 and 90")

    if not -180 <= weather["longitude"] <= 180:
        raise ValueError(f"Invalid longitude {weather['longitude']}: must be between -180 and 180")

    # Validate heat demand map
    if "heat_demand_map" not in config:
        raise ValueError("Missing required section: automation.heat_demand_map")

    heat_demand_map = config["heat_demand_map"]
    if not isinstance(heat_demand_map, list) or len(heat_demand_map) < 2:
        raise ValueError("automation.heat_demand_map must be a list with at least 2 entries")

    # Validate each heat demand entry
    prev_temp = None
    for idx, entry in enumerate(heat_demand_map):
        if not isinstance(entry, dict):
            raise ValueError(f"heat_demand_map[{idx}] must be a dictionary")

        if "outdoor_temp" not in entry or "daily_kwh" not in entry:
            raise ValueError(
                f"heat_demand_map[{idx}] must have 'outdoor_temp' and 'daily_kwh' fields"
            )

        outdoor_temp = entry["outdoor_temp"]
        daily_kwh = entry["daily_kwh"]

        # Validate types and ranges
        if not isinstance(outdoor_temp, (int, float)):
            raise ValueError(f"heat_demand_map[{idx}].outdoor_temp must be a number")

        if not isinstance(daily_kwh, (int, float)) or daily_kwh < 0:
            raise ValueError(f"heat_demand_map[{idx}].daily_kwh must be a positive number")

        # Ensure temperatures are in ascending order
        if prev_temp is not None and outdoor_temp <= prev_temp:
            raise ValueError(
                f"heat_demand_map entries must be in ascending order by outdoor_temp "
                f"(entry {idx}: {outdoor_temp} <= {prev_temp})"
            )

        prev_temp = outdoor_temp

    # Validate night_off_period (singular)
    if "night_off_period" in config:
        period = config["night_off_period"]
        if not isinstance(period, dict):
            raise ValueError("automation.night_off_period must be a dictionary")
        if "start" not in period or "end" not in period:
            raise ValueError("night_off_period must have 'start' and 'end'")
        # Simple format check (HH:MM)
        for key in ["start", "end"]:
            time_str = period[key]
            try:
                parts = time_str.split(":")
                if len(parts) != 2:
                    raise ValueError()
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError()
            except (ValueError, IndexError):
                raise ValueError(f"Invalid time format in night_off_period.{key}: {time_str}")

    # Validate ramping
    if "ramping" in config:
        ramping = config["ramping"]
        if not isinstance(ramping, dict):
            raise ValueError("automation.ramping must be a dictionary")

    # Validate dhw section
    if "dhw" in config:
        dhw = config["dhw"]
        if not isinstance(dhw, dict):
            raise ValueError("automation.dhw must be a dictionary")
        if dhw.get("enabled", False):
            if "start_time" not in dhw or "target_temp" not in dhw:
                raise ValueError("DHW requires 'start_time' and 'target_temp'")
            # Time format check
            time_str = dhw["start_time"]
            try:
                parts = time_str.split(":")
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError()
            except (ValueError, IndexError):
                raise ValueError(f"Invalid DHW start_time: {time_str}")

    # Validate storage section
    if "storage" not in config:
        raise ValueError("Missing required section: automation.storage")

    storage = config["storage"]
    required_storage_fields = ["db_path", "retention_days"]
    for field in required_storage_fields:
        if field not in storage:
            raise ValueError(f"Missing required field: automation.storage.{field}")

    # Validate retention_days
    if not isinstance(storage["retention_days"], int) or storage["retention_days"] < 1:
        raise ValueError("automation.storage.retention_days must be a positive integer")

    logger.info("Automation config validated successfully")


def get_heat_demand_for_temp(heat_demand_map: list[dict[str, float]], outdoor_temp: float) -> float:
    """Calculate heat demand for a given outdoor temperature using linear interpolation.

    Args:
        heat_demand_map: List of {outdoor_temp, daily_kwh} mappings (must be sorted).
        outdoor_temp: Current outdoor temperature in °C.

    Returns:
        Estimated daily heat demand in kWh.
    """
    # Handle edge cases
    if outdoor_temp <= heat_demand_map[0]["outdoor_temp"]:
        return heat_demand_map[0]["daily_kwh"]

    if outdoor_temp >= heat_demand_map[-1]["outdoor_temp"]:
        return heat_demand_map[-1]["daily_kwh"]

    # Linear interpolation
    for i in range(len(heat_demand_map) - 1):
        lower = heat_demand_map[i]
        upper = heat_demand_map[i + 1]

        if lower["outdoor_temp"] <= outdoor_temp <= upper["outdoor_temp"]:
            # Interpolate
            temp_range = upper["outdoor_temp"] - lower["outdoor_temp"]
            kwh_range = upper["daily_kwh"] - lower["daily_kwh"]
            temp_offset = outdoor_temp - lower["outdoor_temp"]

            return lower["daily_kwh"] + (temp_offset / temp_range) * kwh_range

    # Should never reach here if map is valid
    return heat_demand_map[-1]["daily_kwh"]
