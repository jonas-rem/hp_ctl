import logging
from typing import Any

from src.hp_ctl.protocol import FieldSpec, Message

logger = logging.getLogger(__name__)


class HomeAssistantMapper:
    """Maps decoded messages to Home Assistant MQTT Discovery format."""

    def __init__(self, device_id: str = "aquarea_k", device_name: str = "Aquarea K") -> None:
        """Initialize Home Assistant mapper.

        Args:
            device_id: Unique device identifier for Home Assistant.
            device_name: Human-readable device name.
        """
        self.device_id = device_id
        self.device_name = device_name

    def get_state_topic_prefix(self) -> str:
        """Get the MQTT topic prefix for state updates.

        Returns:
            Topic prefix aligned with device_id.
        """
        return f"{self.device_id}/state"

    def message_to_ha_discovery(
        self, fields: list[FieldSpec]
    ) -> dict[str, dict]:
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
            updates[topic] = value
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
            "state_topic": f"{self.get_state_topic_prefix()}/{field.name}",
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

