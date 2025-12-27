# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Heating control algorithm for autonomous heat pump optimization."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AutomationAction:
    """Represents a set of commands suggested by the algorithm."""

    hp_status: Optional[str] = None  # "On" or "Off"
    target_temp: Optional[float] = None
    reason: str = "No action"


class HeatingAlgorithm:
    """Core logic for heat pump control."""

    def __init__(self, config: dict) -> None:
        """Initialize algorithm with configuration."""
        self.config = config

    def is_in_night_off_period(self, current_time: datetime) -> bool:
        """Check if current time is within a night-off period."""
        night_off_periods = self.config.get("night_off_periods", [])
        now_time = current_time.strftime("%H:%M")

        for period in night_off_periods:
            start = period["start"]
            end = period["end"]

            if start <= end:
                if start <= now_time <= end:
                    return True
            else:  # Overlaps midnight (e.g., 22:00 - 06:00)
                if now_time >= start or now_time <= end:
                    return True
        return False

    def decide(
        self,
        current_time: datetime,
        outdoor_temp_avg_24h: float,
        actual_heat_kwh_today: float,
        estimated_demand_kwh: float,
        current_outlet_temp: float,
        current_inlet_temp: float,
        zone1_actual_temp: float,
        current_hp_status: str,
        heat_power_generation: float,
        heat_power_consumption: float,
    ) -> AutomationAction:
        """Decide on the next heat pump action.

        Args:
            current_time: Current datetime.
            outdoor_temp_avg_24h: 24h average outdoor temperature.
            actual_heat_kwh_today: Actual heat generated today so far.
            estimated_demand_kwh: Calculated daily demand.
            current_outlet_temp: Current outlet water temperature.
            current_inlet_temp: Current inlet water temperature.
            zone1_actual_temp: Zone 1 actual temperature (e.g. buffer middle).
            current_hp_status: Current heat pump status ("On"/"Off").
            heat_power_generation: Momentary heat generation in Watts.
            heat_power_consumption: Momentary electrical consumption in Watts.

        Returns:
            AutomationAction with suggested status and target temp.
        """
        # 1. Night-Off Check
        if self.is_in_night_off_period(current_time):
            return AutomationAction(hp_status="Off", reason="Night-off period active")

        # 2. Demand Check (Bucket Logic)
        if actual_heat_kwh_today >= estimated_demand_kwh:
            return AutomationAction(hp_status="Off", reason="Daily heat demand met")

        # 3. Target Temperature Calculation
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
            suggested_target = zone1_actual_temp
            reason_detail = f"delta_t ({delta_t:.1f}K) > min ({min_delta_t}K)"
        else:
            suggested_target = zone1_actual_temp + 1.0
            reason_detail = f"delta_t ({delta_t:.1f}K) <= min ({min_delta_t}K)"

        return AutomationAction(
            hp_status="On",
            target_temp=round(suggested_target, 1),
            reason=f"Heating: {reason_detail}",
        )
