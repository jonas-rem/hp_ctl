# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Heating control algorithm for autonomous heat pump optimization."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Default values for heating start time calculation
DEFAULT_LATEST_START = "13:00"  # Default latest start if DHW not configured
COLD_THRESHOLD = 5.0  # °C - at or below this, start at earliest time
WARM_THRESHOLD_OFFSET = 3.0  # °C below max temp in heat_demand_map

# Protocol absolute minimum temperatures (heat pump hard limits)
PROTOCOL_MIN_HEAT_TEMP = 20.0  # °C - absolute minimum for zone1_heat_target_temp
PROTOCOL_MIN_DHW_TEMP = 40.0  # °C - absolute minimum for dhw_target_temp

# User configurable default minimums (can be overridden in config)
DEFAULT_MIN_HEAT_TEMP = 25.0  # °C - default user minimum for zone1_heat_target_temp
DEFAULT_MIN_DHW_TEMP = 37.0  # °C - default user minimum for dhw_target_temp


def _time_str_to_minutes(time_str: str) -> int:
    """Convert "HH:MM" to minutes since midnight.

    Args:
        time_str: Time string in "HH:MM" format.

    Returns:
        Minutes since midnight.
    """
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


def _minutes_to_time_str(minutes: int) -> str:
    """Convert minutes since midnight to "HH:MM".

    Args:
        minutes: Minutes since midnight.

    Returns:
        Time string in "HH:MM" format.
    """
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


@dataclass
class AutomationAction:
    """Represents a set of commands suggested by the algorithm."""

    hp_status: Optional[str] = None  # "On" or "Off"
    operating_mode: Optional[str] = None
    target_temp: Optional[float] = None
    dhw_target_temp: Optional[float] = None
    reason: str = "No action"


class HeatingAlgorithm:
    """Core logic for heat pump control."""

    def __init__(self, config: dict) -> None:
        """Initialize algorithm with configuration."""
        self.config = config

        # Get user-configured minimum temperatures from limits section
        limits = config.get("limits", {})
        heat_limits = limits.get("zone1_heat_target_temp", {})
        dhw_limits = limits.get("dhw_target_temp", {})

        # Use configured min or default, but never below protocol minimum
        self.min_heat_temp = max(
            heat_limits.get("min", DEFAULT_MIN_HEAT_TEMP),
            PROTOCOL_MIN_HEAT_TEMP
        )
        self.min_dhw_temp = max(
            dhw_limits.get("min", DEFAULT_MIN_DHW_TEMP),
            PROTOCOL_MIN_DHW_TEMP
        )

        # Protocol maximums from FieldSpec definitions
        self.protocol_max_heat = 65.0
        self.protocol_max_dhw = 75.0

    def is_in_night_off_period(self, current_time: datetime) -> bool:
        """Check if current time is within the night-off period.

        Args:
            current_time: Current datetime to check.

        Returns:
            True if within night-off period, False otherwise.
        """
        period = self.config.get("night_off_period")
        if not period:
            return False

        now_time = current_time.strftime("%H:%M")
        start = period["start"]
        end = period["end"]

        if start <= end:
            # Same day period (e.g., 10:00 - 14:00)
            return start <= now_time <= end
        else:
            # Overlaps midnight (e.g., 22:00 - 06:00)
            return now_time >= start or now_time <= end

    def calculate_heating_start_time(self, outdoor_temp_forecast_24h: float) -> tuple[str, str]:
        """Calculate dynamic heating start time based on outdoor temperature.

        The heating start time is interpolated between:
        - Earliest: end of night_off_period (e.g., "07:30")
        - Latest: DHW start_time or default "13:00"

        Temperature thresholds:
        - <= 0°C: Start at earliest time (full heat budget needed)
        - >= warm threshold (max temp in heat_demand_map - 3°C): Start at latest time

        Args:
            outdoor_temp_forecast_24h: 24h average outdoor temperature in °C.

        Returns:
            Tuple of (start_time "HH:MM", reason string for logging).
        """
        # Get boundaries from config
        night_off = self.config.get("night_off_period", {})
        earliest_start = night_off.get("end", "07:30")

        dhw_config = self.config.get("dhw", {})
        if dhw_config.get("enabled", False):
            latest_start = dhw_config.get("start_time", DEFAULT_LATEST_START)
        else:
            latest_start = DEFAULT_LATEST_START

        # Determine warm threshold from heat_demand_map
        heat_demand_map = self.config.get("heat_demand_map", [])
        if heat_demand_map:
            max_temp = heat_demand_map[-1]["outdoor_temp"]
            warm_threshold = max_temp - WARM_THRESHOLD_OFFSET
        else:
            warm_threshold = 17.0  # Fallback

        # Handle boundary cases
        if outdoor_temp_forecast_24h <= COLD_THRESHOLD:
            return (
                earliest_start,
                f"cold day ({outdoor_temp_forecast_24h:.1f}C <= {COLD_THRESHOLD}C)",
            )

        if outdoor_temp_forecast_24h >= warm_threshold:
            return latest_start, f"warm day ({outdoor_temp_forecast_24h:.1f}C >= {warm_threshold}C)"

        # Linear interpolation between thresholds
        temp_range = warm_threshold - COLD_THRESHOLD
        temp_offset = outdoor_temp_forecast_24h - COLD_THRESHOLD
        fraction = temp_offset / temp_range  # 0.0 = cold, 1.0 = warm

        # Convert times to minutes, interpolate, convert back
        earliest_mins = _time_str_to_minutes(earliest_start)
        latest_mins = _time_str_to_minutes(latest_start)
        target_mins = earliest_mins + fraction * (latest_mins - earliest_mins)

        start_time = _minutes_to_time_str(int(target_mins))
        reason = (
            f"interpolated ({outdoor_temp_forecast_24h:.1f}C in {COLD_THRESHOLD}-{warm_threshold}C)"
        )

        return start_time, reason

    def is_before_heating_start(self, current_time: datetime, heating_start: str) -> bool:
        """Check if current time is in the delayed start window.

        Only applies after night_off_period ends but before heating_start.
        This creates a morning window where the HP stays off on warmer days.

        Args:
            current_time: Current datetime to check.
            heating_start: Calculated heating start time in "HH:MM" format.

        Returns:
            True if in delayed start window (HP should stay off), False otherwise.
        """
        period = self.config.get("night_off_period")
        if not period:
            return False

        night_off_end = period["end"]
        now_time = current_time.strftime("%H:%M")

        # Only apply during morning window (after night-off ends, before heating start)
        # This handles the simple case: night_off_end < now < heating_start
        if night_off_end <= now_time < heating_start:
            return True

        return False

    def decide(
        self,
        current_time: datetime,
        outdoor_temp_forecast_24h: float,
        actual_heat_kwh_today: float,
        estimated_demand_kwh: float,
        current_outlet_temp: float,
        current_inlet_temp: float,
        zone1_actual_temp: float,
        current_hp_status: str,
        current_operating_mode: str,
        three_way_valve: str,
        heat_power_generation: float,
        heat_power_consumption: float,
    ) -> AutomationAction:
        """Decide on the next heat pump action.

        Args:
            current_time: Current datetime.
            outdoor_temp_forecast_24h: 24h average outdoor temperature.
            actual_heat_kwh_today: Actual heat generated today so far.
            estimated_demand_kwh: Calculated daily demand.
            current_outlet_temp: Current outlet water temperature.
            current_inlet_temp: Current inlet water temperature.
            zone1_actual_temp: Zone 1 actual temperature (e.g. buffer middle).
            current_hp_status: Current heat pump status ("On"/"Off").
            current_operating_mode: Current operating mode.
            three_way_valve: Current 3-way valve position ("Room"/"DHW").
            heat_power_generation: Momentary heat generation in Watts.
            heat_power_consumption: Momentary electrical consumption in Watts.

        Returns:
            AutomationAction with suggested status and target temp.
        """
        # 1. Night-Off Check (actual night hours)
        if self.is_in_night_off_period(current_time):
            return AutomationAction(hp_status="Off", reason="Night-off period active")

        # 2. Dynamic Start Time Check (morning delayed start)
        heating_start, _ = self.calculate_heating_start_time(outdoor_temp_forecast_24h)
        if self.is_before_heating_start(current_time, heating_start):
            return AutomationAction(
                hp_status="Off",
                reason=f"Delayed start until {heating_start}",
            )

        # 3. DHW Logic (Priority)
        dhw_config = self.config.get("dhw", {})
        if dhw_config.get("enabled", False):
            start_time_str = dhw_config["start_time"]
            now_time = current_time.time()

            # Trigger DHW within a 10-minute window starting at start_time.
            # Once DHW completes (valve returns to Room), mode reverts to Heat.
            # Re-triggering within the window is harmless as water is already hot.
            trigger_start = datetime.strptime(start_time_str, "%H:%M").time()
            trigger_end = (
                datetime.combine(datetime.min, trigger_start) + timedelta(minutes=10)
            ).time()

            if trigger_start <= now_time <= trigger_end:
                if "DHW" not in current_operating_mode:
                    # Clamp DHW target temp to valid range
                    dhw_target = dhw_config["target_temp"]
                    dhw_target = max(dhw_target, self.min_dhw_temp)
                    dhw_target = min(dhw_target, self.protocol_max_dhw)

                    return AutomationAction(
                        hp_status="On",
                        operating_mode="Heat+DHW",
                        dhw_target_temp=dhw_target,
                        reason=f"DHW trigger window ({start_time_str}-{trigger_end.strftime('%H:%M')})",
                    )
            # Switch back to Heat only if DHW is finished (valve is Room)
            # and we are past the trigger window
            elif "DHW" in current_operating_mode and three_way_valve == "Room":
                return AutomationAction(
                    operating_mode="Heat",
                    reason="DHW finished",
                )

        # 4. Demand Check (Bucket Logic)
        if actual_heat_kwh_today >= estimated_demand_kwh:
            return AutomationAction(hp_status="Off", reason="Heat demand met")

        # 5. Target Temperature Calculation
        ramping_config = self.config.get("ramping", {})
        min_delta_t = ramping_config.get("min_delta_t", 3.0)

        # Algorithm Logic:
        # If delta_t (outlet - inlet) > min_delta_t, we are heating effectively.
        # In this case, we set the target to the current actual temperature
        # to maintain the state.
        # Otherwise, we increase the target temperature by 1K relative to
        # the current actual temperature to nudge the compressor frequency up.
        delta_t = current_outlet_temp - current_inlet_temp
        if delta_t > min_delta_t:
            target_temp = zone1_actual_temp
            reason_detail = f"delta_t: {delta_t:.1f}K; t: {target_temp} °C"
        else:
            target_temp = zone1_actual_temp + 1.0
            reason_detail = f"delta_t ({delta_t:.1f}K) <= min ({min_delta_t}K)"

        # Clamp target temperature to configured minimum and protocol maximum
        original_target = target_temp
        target_temp = max(target_temp, self.min_heat_temp)
        target_temp = min(target_temp, self.protocol_max_heat)

        if target_temp != original_target:
            reason_detail += f" (clamped {original_target:.1f}°C → {target_temp:.1f}°C)"
            logger.debug(
                "Target temp clamped: %.1f°C → %.1f°C (min=%.1f°C)",
                original_target,
                target_temp,
                self.min_heat_temp,
            )

        return AutomationAction(
            hp_status="On",
            target_temp=round(target_temp, 1),
            reason=f"Heating: {reason_detail}",
        )
