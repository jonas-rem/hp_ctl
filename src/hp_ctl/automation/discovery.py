# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Home Assistant MQTT Discovery for automation entities."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AutomationDiscovery:
    """Generates Home Assistant MQTT Discovery configs for automation entities."""

    def __init__(
        self,
        device_id: str,
        device_name: str,
        topic_prefix: str = "hp_ctl",
    ) -> None:
        """Initialize automation discovery.

        Args:
            device_id: Main device identifier (heat pump).
            device_name: Main device name.
            topic_prefix: MQTT topic prefix.
        """
        self.device_id = device_id
        self.device_name = device_name
        self.topic_prefix = topic_prefix
        self.automation_device_id = f"{device_id}_automation"
        self.automation_device_name = f"{device_name} Automation"
        self.base_topic = f"{topic_prefix}/{device_id}/automation"

    def get_discovery_configs(self) -> dict[str, Any]:
        """Generate discovery configs for all automation entities.

        Returns:
            Dictionary of {topic: payload} for MQTT publishing.
        """
        device_info: dict[str, Any] = {
            "identifiers": [self.automation_device_id],
            "name": self.automation_device_name,
            "manufacturer": "hp-ctl",
            "via_device": self.device_id,
        }

        configs: dict[str, Any] = {}

        # 1. Mode Select
        mode_key = "mode"
        topic = f"homeassistant/select/{self.automation_device_id}/{mode_key}/config"
        configs[topic] = {
            "name": "Mode",
            "unique_id": f"{self.automation_device_id}_{mode_key}",
            "state_topic": f"{self.base_topic}/{mode_key}",
            "command_topic": f"{self.base_topic}/{mode_key}/set",
            "options": ["manual", "automatic"],
            "icon": "mdi:auto-mode",
            "optimistic": False,
            "device": device_info,
        }

        # Helper for sensors
        def add_sensor(
            key: str,
            name: str,
            unit: Optional[str] = None,
            device_class: Optional[str] = None,
            state_class: Optional[str] = None,
            icon: Optional[str] = None,
            topic_path: Optional[str] = None,
        ) -> None:
            full_path = f"{self.base_topic}/{topic_path or key}"
            config = {
                "name": name,
                "unique_id": f"{self.automation_device_id}_{key.replace('/', '_')}",
                "state_topic": full_path,
                "device": device_info,
            }
            if unit:
                config["unit_of_measurement"] = unit
            if device_class:
                config["device_class"] = device_class
            if state_class:
                config["state_class"] = state_class
            if icon:
                config["icon"] = icon
            conf_topic = (
                f"homeassistant/sensor/{self.automation_device_id}/{key.replace('/', '_')}/config"
            )
            configs[conf_topic] = config

        # 2. Weather & Demand
        add_sensor(
            "outdoor_temp_avg_24h",
            "Outdoor Temperature (24h Avg)",
            unit="°C",
            device_class="temperature",
            state_class="measurement",
        )
        add_sensor("weather_date", "Weather Date", icon="mdi:calendar")
        add_sensor(
            "estimated_daily_demand",
            "Estimated Daily Demand",
            unit="kWh",
            device_class="energy",
            state_class="total",
        )
        add_sensor(
            "active_target_temp",
            "Active Target Temperature",
            unit="°C",
            device_class="temperature",
            state_class="measurement",
            icon="mdi:target",
        )
        add_sensor("reason", "Automation Reason", icon="mdi:information-outline")

        # 3. Today's Running Totals
        add_sensor(
            "today/total_heat_kwh",
            "Total Heat Energy Today",
            unit="kWh",
            device_class="energy",
            state_class="total_increasing",
            topic_path="today/total_heat_kwh",
        )
        add_sensor(
            "today/total_consumption_kwh",
            "Total Consumption Today",
            unit="kWh",
            device_class="energy",
            state_class="total_increasing",
            topic_path="today/total_consumption_kwh",
        )
        add_sensor(
            "today/avg_cop",
            "Average COP Today",
            state_class="measurement",
            icon="mdi:speedometer",
            topic_path="today/avg_cop",
        )
        add_sensor(
            "today/runtime_hours",
            "Runtime Today",
            unit="h",
            device_class="duration",
            state_class="total_increasing",
            icon="mdi:clock-outline",
            topic_path="today/runtime_hours",
        )

        return configs
