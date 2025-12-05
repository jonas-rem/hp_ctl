# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import json
import logging

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MqttClient:
    """MQTT client for publishing decoded messages."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        topic_prefix: str = "hp_ctl",
    ) -> None:
        """Initialize MQTT client.

        Args:
            broker: MQTT broker hostname or IP.
            port: MQTT broker port. Defaults to 1883.
            topic_prefix: Topic prefix for published messages. Defaults to 'hp_ctl'.
        """
        self.broker = broker
        self.port = port
        self.topic_prefix = topic_prefix
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.connected = False

    def connect(self) -> None:
        """Connect to MQTT broker."""
        logger.debug("Connecting to MQTT broker: %s:%d", self.broker, self.port)
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        logger.debug("Disconnecting from MQTT broker")
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic: str, payload: dict | str) -> None:
        """Publish message to MQTT topic.

        Args:
            topic: Topic name. If it starts with 'homeassistant/', it's used as-is.
                   Otherwise, it's prefixed with topic_prefix.
            payload: Dictionary to publish as JSON, or string to publish as-is.
        """
        # Don't add prefix for Home Assistant discovery topics
        if topic.startswith("homeassistant/"):
            full_topic = topic
        else:
            full_topic = f"{self.topic_prefix}/{topic}"

        # Convert payload to string if it's a dict
        if isinstance(payload, dict):
            mqtt_payload = json.dumps(payload)
        else:
            mqtt_payload = str(payload)

        logger.debug("Publishing to %s: %s", full_topic, mqtt_payload)
        self.client.publish(full_topic, mqtt_payload, qos=1)

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        """Callback for when client connects to broker."""
        if reason_code == 0:
            logger.info("Connected to MQTT broker: %s:%d", self.broker, self.port)
            self.connected = True
        else:
            logger.warning("Failed to connect to MQTT broker: %s", reason_code)
            self.connected = False

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Callback for when client disconnects from broker."""
        logger.info("Disconnected from MQTT broker")
        self.connected = False
