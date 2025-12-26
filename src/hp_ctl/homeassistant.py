# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import logging
from typing import Any, Optional

from hp_ctl.protocol import FieldSpec, Message

logger = logging.getLogger(__name__)


class HomeAssistantMapper:
    """Maps decoded messages to Home Assistant MQTT Discovery format."""

    def __init__(
        self,
        device_id: str = "aquarea_k",
        device_name: str = "Aquarea K",
        topic_prefix: str = "hp_ctl",
    ) -> None:
        """Initialize Home Assistant mapper.

        Args:
            device_id: Unique device identifier for Home Assistant.
            device_name: Human-readable device name.
            topic_prefix: MQTT topic prefix (must match MqttClient).
        """
        self.device_id = device_id
        self.device_name = device_name
        self.topic_prefix = topic_prefix

    def get_state_topic_prefix(self) -> str:
        """Get the MQTT topic prefix for state updates (relative).

        Returns:
            Topic prefix (relative, will be prefixed by MqttClient).
        """
        return f"{self.device_id}/state"

    def get_full_state_topic_prefix(self) -> str:
        """Get the full MQTT topic prefix including hp_ctl prefix.

        Returns:
            Full absolute topic prefix for discovery configs.
        """
        return f"{self.topic_prefix}/{self.device_id}/state"

    def message_to_ha_discovery(self, fields: list[FieldSpec]) -> dict[str, dict]:
        """Convert field specs to Home Assistant MQTT Discovery configs.

        Args:
            fields: List of FieldSpec definitions.

        Returns:
            Dictionary of {topic: payload} for publishing discovery configs.
        """
        configs = {}
        for field in fields:
            topic = f"homeassistant/sensor/{self.device_id}/{field.name}/config"
            payload = self._create_discovery_config(field)
            configs[topic] = payload
        logger.debug("Generated %d Home Assistant discovery configs", len(configs))
        return configs

    def message_to_state_updates(self, message: Message) -> dict[str, Any]:
        """Convert Message fields to state update payloads.

        Args:
            message: Decoded message with field values.

        Returns:
            Dictionary of {topic: value} for publishing state updates.
        """
        updates = {}
        prefix = self.get_state_topic_prefix()
        for field_name, value in message.fields.items():
            topic = f"{prefix}/{field_name}"
            # Convert value to string for MQTT publishing
            # Booleans become "ON"/"OFF", None becomes empty string
            if isinstance(value, bool):
                updates[topic] = "ON" if value else "OFF"
            elif value is None:
                updates[topic] = ""
            else:
                updates[topic] = str(value)
        logger.debug("Generated %d state updates", len(updates))
        return updates

    def _create_discovery_config(self, field: FieldSpec) -> dict:
        """Create Home Assistant MQTT Discovery config for a field.

        Args:
            field: FieldSpec to create config for.

        Returns:
            Home Assistant discovery config dictionary.
        """
        config = {
            "name": field.name.replace("_", " ").title(),
            "state_topic": f"{self.get_full_state_topic_prefix()}/{field.name}",
            "unique_id": f"{self.device_id}_{field.name}",
            "device": {
                "identifiers": [self.device_id],
                "name": self.device_name,
                "manufacturer": "Panasonic",
            },
        }

        # Add unit if present
        if field.unit:
            config["unit_of_measurement"] = field.unit

        # Add device class if present
        if field.ha_class:
            config["device_class"] = field.ha_class

        # Add state class if present
        if field.ha_state_class:
            config["state_class"] = field.ha_state_class

        # Add icon if present
        if field.ha_icon:
            config["icon"] = field.ha_icon

        logger.debug("Created HA discovery config for %s", field.name)
        return config

    def get_command_topic_prefix(self) -> str:
        """Get the MQTT topic prefix for commands (relative)."""
        return f"{self.device_id}/set"

    def get_full_command_topic_prefix(self) -> str:
        """Get the full MQTT topic prefix including hp_ctl prefix."""
        return f"{self.topic_prefix}/{self.device_id}/set"

    def writable_fields_to_ha_discovery(
        self, fields: list[FieldSpec], user_limits: Optional[dict] = None
    ) -> dict[str, dict]:
        """Generate discovery configs for writable fields.

        Returns:
            Dictionary of {topic: payload} for MQTT publishing.
        """
        configs = {}
        for field in fields:
            if not field.writable:
                continue

            # Determine entity type
            if field.options is not None:
                if len(field.options) == 2 and set(field.options) == {"On", "Off"}:
                    # Binary → switch
                    topic = f"homeassistant/switch/{self.device_id}/{field.name}/config"
                    configs[topic] = self._create_switch_config(field)
                else:
                    # Multi-option → select
                    topic = f"homeassistant/select/{self.device_id}/{field.name}/config"
                    configs[topic] = self._create_select_config(field)
            else:
                # Numeric → number
                topic = f"homeassistant/number/{self.device_id}/{field.name}/config"
                configs[topic] = self._create_number_config(field, user_limits)

        return configs

    def _create_number_config(self, field: FieldSpec, user_limits: Optional[dict]) -> dict:
        """Create discovery config for number entity."""
        # Use stricter of protocol vs user-defined limits
        min_val = field.min_value
        max_val = field.max_value

        if user_limits and field.name in user_limits:
            limit_config = user_limits[field.name]
            if isinstance(limit_config, dict) and "max" in limit_config:
                max_val = min(max_val, limit_config["max"]) if max_val else limit_config["max"]

        return {
            "name": field.name.replace("_", " ").title(),
            "unique_id": f"{self.device_id}_{field.name}",
            "state_topic": f"{self.get_full_state_topic_prefix()}/{field.name}",
            "command_topic": f"{self.get_full_command_topic_prefix()}/{field.name}",
            "min": min_val,
            "max": max_val,
            "step": 1,
            "unit_of_measurement": field.unit,
            "device_class": field.ha_class,
            "icon": field.ha_icon,
            "optimistic": True,  # Fast feedback
            "device": {
                "identifiers": [self.device_id],
                "name": self.device_name,
                "manufacturer": "Panasonic",
            },
        }

    def _create_select_config(self, field: FieldSpec) -> dict:
        """Create discovery config for select entity."""
        return {
            "name": field.name.replace("_", " ").title(),
            "unique_id": f"{self.device_id}_{field.name}",
            "state_topic": f"{self.get_full_state_topic_prefix()}/{field.name}",
            "command_topic": f"{self.get_full_command_topic_prefix()}/{field.name}",
            "options": field.options,
            "icon": field.ha_icon,
            "optimistic": True,
            "device": {
                "identifiers": [self.device_id],
                "name": self.device_name,
                "manufacturer": "Panasonic",
            },
        }

    def _create_switch_config(self, field: FieldSpec) -> dict:
        """Create discovery config for switch entity."""
        return {
            "name": field.name.replace("_", " ").title(),
            "unique_id": f"{self.device_id}_{field.name}",
            "state_topic": f"{self.get_full_state_topic_prefix()}/{field.name}",
            "command_topic": f"{self.get_full_command_topic_prefix()}/{field.name}",
            "payload_on": "On",
            "payload_off": "Off",
            "state_on": "On",
            "state_off": "Off",
            "icon": field.ha_icon,
            "optimistic": True,
            "device": {
                "identifiers": [self.device_id],
                "name": self.device_name,
                "manufacturer": "Panasonic",
            },
        }
