# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import logging
import signal
import sys
import time
from typing import Any, Optional

from hp_ctl.config import load_config
from hp_ctl.homeassistant import HomeAssistantMapper
from hp_ctl.mqtt import MqttClient
from hp_ctl.protocol import EXTRA_FIELDS, STANDARD_FIELDS, FieldSpec, HeatPumpProtocol, Message
from hp_ctl.uart import UartTransceiver

logger = logging.getLogger(__name__)
LOGLEVEL = logging.DEBUG


# Retry configuration
RETRY_INTERVAL = 3  # seconds
MAX_RETRIES = None  # None = infinite retries


class Application:
    """Main application orchestrating UART, protocol decoding, and MQTT publishing."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        """Initialize application with configuration.

        Args:
            config_path: Path to config.yaml file.
        """
        self.config = load_config(config_path)
        self.protocol = HeatPumpProtocol(user_limits=self.config.get("limits"))
        self.mqtt_client: Optional[MqttClient] = None
        self.uart_transceiver: Optional[UartTransceiver] = None
        self.ha_mapper = HomeAssistantMapper()
        self.discovery_published = False

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received (%d)", signum)
        self.shutdown()
        sys.exit(0)

    def _publish_discovery(self) -> None:
        """Publish Home Assistant discovery configs.

        Called on every MQTT connection (initial and reconnects) to ensure
        Home Assistant always has the latest device configurations.
        """
        if self.mqtt_client:
            logger.info("Publishing Home Assistant discovery configs")
            # Publish configs for both standard and extra fields
            all_fields = STANDARD_FIELDS + EXTRA_FIELDS
            discovery_configs = self.ha_mapper.message_to_ha_discovery(all_fields)
            for topic, payload in discovery_configs.items():
                self.mqtt_client.publish(topic, payload)

            # Publish writable entity discovery (NEW)
            writable_configs = self.ha_mapper.writable_fields_to_ha_discovery(
                STANDARD_FIELDS, user_limits=self.config.get("limits")
            )
            for topic, payload in writable_configs.items():
                self.mqtt_client.publish(topic, payload)

            logger.info(
                "Published %d discovery configs", len(discovery_configs) + len(writable_configs)
            )
            self.discovery_published = True

    def _get_field_by_name(self, name: str) -> FieldSpec:
        """Find field spec by name in STANDARD_FIELDS."""
        for field in STANDARD_FIELDS:
            if field.name == name:
                return field
        raise ValueError(f"Unknown field: {name}")

    def _on_mqtt_command(self, topic: str, payload: str) -> None:
        """Handle incoming MQTT commands from Home Assistant.

        Args:
            topic: Command topic (e.g., "hp_ctl/aquarea_k/set/dhw_target_temp")
            payload: Command value (string representation)
        """
        # Extract field name from topic
        # Format: hp_ctl/aquarea_k/set/{field_name}
        field_name = topic.rsplit("/", 1)[-1]

        try:
            # Get field spec
            field = self._get_field_by_name(field_name)

            # Convert payload to appropriate type
            value: Any
            if field.options is not None:
                # String for enum fields (already correct type)
                value = payload
            else:
                # Integer for temperature fields
                # HA might send "45.0", handle it
                value = int(float(payload))

            # Validate and encode
            message = Message(packet_type=0x10, fields={field_name: value})
            encoded = self.protocol.standard_codec.encode(message)

            # Send via UART
            if self.uart_transceiver:
                self.uart_transceiver.send(encoded)
                logger.info("Sent command: %s = %s", field_name, value)
            else:
                logger.warning("UART not ready, cannot send command")

        except ValueError as e:
            logger.warning("Invalid command %s=%s: %s", field_name, payload, e)
        except Exception as e:
            logger.exception("Failed to send command %s=%s: %s", field_name, payload, e)

    def _on_mqtt_connect(self) -> None:
        """Callback on MQTT connection - publish discovery and subscribe to commands."""
        self._publish_discovery()

        # Subscribe to command topics
        if self.mqtt_client:
            command_topic = f"{self.ha_mapper.get_full_command_topic_prefix()}/#"
            self.mqtt_client.subscribe(command_topic)
            logger.info("Subscribed to: %s", command_topic)

    def _on_uart_message(self, raw_msg: bytes) -> None:
        """Callback invoked when UART receives a valid message.

        Args:
            raw_msg: Raw validated message bytes from UART.
        """
        try:
            # Decode message
            message = self.protocol.decode(raw_msg)

            # Publish state updates
            if self.mqtt_client:
                state_updates = self.ha_mapper.message_to_state_updates(message)
                for topic, value in state_updates.items():
                    self.mqtt_client.publish(topic, value)
                logger.debug("Published %d state updates", len(state_updates))

        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Error processing UART message: %s", e)

    def run(self) -> None:
        """Start the application and run main loop with retry logic."""
        retry_count = 0

        while MAX_RETRIES is None or retry_count < MAX_RETRIES:
            try:
                # Initialize MQTT with on_connect callback for discovery publishing
                # The callback fires on every connection (initial + reconnects),
                # ensuring Home Assistant always has the latest discovery configs
                mqtt_config = self.config["mqtt"]
                self.mqtt_client = MqttClient(
                    broker=mqtt_config["broker"],
                    port=mqtt_config["port"],
                    on_connect=self._on_mqtt_connect,
                    on_message=self._on_mqtt_command,
                )
                self.mqtt_client.connect()
                logger.info("MQTT client connected")

                # Initialize UART with callback
                uart_config = self.config["uart"]
                self.uart_transceiver = UartTransceiver(
                    port=uart_config["port"],
                    baudrate=uart_config["baudrate"],
                    on_message=self._on_uart_message,
                    poll_interval=0.1,
                )
                logger.info("UART receiver started on %s", uart_config["port"])

                # Reset retry count on successful connection
                retry_count = 0

                # Keep application running
                logger.info("Application running. Press Ctrl+C to exit.")
                signal.pause()

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self.shutdown()
                sys.exit(0)
            except Exception as e:  # pylint: disable=broad-except
                retry_count += 1

                if MAX_RETRIES is not None and retry_count >= MAX_RETRIES:
                    logger.exception("Max retries reached, exiting: %s", e)
                    self.shutdown()
                    sys.exit(1)

                logger.warning(
                    "Connection failed (attempt %d), retrying in %d seconds: %s",
                    retry_count,
                    RETRY_INTERVAL,
                    str(e),
                )
                time.sleep(RETRY_INTERVAL)

    def shutdown(self) -> None:
        """Shutdown application and cleanup resources."""
        logger.info("Shutting down application")
        if self.uart_transceiver:
            self.uart_transceiver.close()
        if self.mqtt_client:
            self.mqtt_client.disconnect()
        logger.info("Application shutdown complete")


def main() -> None:
    """Entry point for the application."""
    logging.basicConfig(
        level=LOGLEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    app = Application(config_path="config.yaml")
    app.run()


if __name__ == "__main__":
    main()
