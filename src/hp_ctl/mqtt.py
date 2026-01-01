# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import json
import logging
from typing import Callable, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MqttClient:
    """MQTT client for publishing decoded messages."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        topic_prefix: str = "hp_ctl",
        on_connect: Optional[Callable[[], None]] = None,
    ) -> None:
        """Initialize MQTT client.

        Args:
            broker: MQTT broker hostname or IP.
            port: MQTT broker port. Defaults to 1883.
            topic_prefix: Topic prefix for published messages. Defaults to 'hp_ctl'.
            on_connect: Optional callback invoked on each successful connection.
                        Useful for re-publishing discovery configs after reconnection.
        """
        self.broker = broker
        self.port = port
        self.topic_prefix = topic_prefix
        self.on_connect_callback = on_connect
        self._message_listeners: list[tuple[Callable[[str, str], None], Optional[str]]] = []
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
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

    def subscribe(self, topic: str) -> None:
        """Subscribe to a topic pattern.

        Args:
            topic: MQTT topic to subscribe to (can include wildcards).
        """
        logger.debug("Subscribing to: %s", topic)
        self.client.subscribe(topic, qos=1)

    def add_message_listener(
        self, callback: Callable[[str, str], None], topic_filter: Optional[str] = None
    ) -> None:
        """Add a message listener with optional topic filter.

        Args:
            callback: Function to call when a message is received.
                      Args: (topic, payload)
            topic_filter: Optional MQTT topic pattern to filter messages.
                         Only messages matching this pattern will be sent to callback.
                         Supports MQTT wildcards (+ and #).
                         If None, callback receives all messages.
        """
        self._message_listeners.append((callback, topic_filter))

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        topic = msg.topic
        payload = msg.payload.decode()
        logger.debug("Received message: %s = %s", topic, payload)

        for listener, topic_filter in self._message_listeners:
            # Check if listener should receive this message
            if topic_filter is not None and not self._topic_matches(topic, topic_filter):
                continue

            try:
                listener(topic, payload)
            except Exception as e:
                logger.exception("Error in message listener: %s", e)

    def _topic_matches(self, topic: str, pattern: str) -> bool:
        """Check if topic matches MQTT pattern with wildcards.

        Args:
            topic: Actual topic (e.g., "hp_ctl/aquarea_k/set/hp_status")
            pattern: Pattern with wildcards (e.g., "hp_ctl/+/set/#")

        Returns:
            True if topic matches pattern
        """
        topic_parts = topic.split("/")
        pattern_parts = pattern.split("/")

        # If pattern doesn't end with #, lengths must match
        if pattern_parts[-1] != "#" and len(topic_parts) != len(pattern_parts):
            return False

        for i, pattern_part in enumerate(pattern_parts):
            # # matches everything remaining
            if pattern_part == "#":
                return True

            # Check if we have more pattern parts but topic ended
            if i >= len(topic_parts):
                return False

            # + matches any single level
            if pattern_part == "+":
                continue

            # Exact match required
            if pattern_part != topic_parts[i]:
                return False

        return True

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        """Callback for when client connects to broker."""
        if reason_code == 0:
            logger.info("Connected to MQTT broker: %s:%d", self.broker, self.port)
            self.connected = True
            # Invoke callback on every successful connection (initial + reconnect)
            if self.on_connect_callback:
                logger.debug("Invoking on_connect callback")
                self.on_connect_callback()
        else:
            logger.warning("Failed to connect to MQTT broker: %s", reason_code)
            self.connected = False

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Callback for when client disconnects from broker."""
        logger.info("Disconnected from MQTT broker")
        self.connected = False
