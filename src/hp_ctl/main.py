import logging
import signal
import sys
import time
from typing import Optional

from hp_ctl.config import load_config
from hp_ctl.homeassistant import HomeAssistantMapper
from hp_ctl.mqtt import MqttClient
from hp_ctl.protocol import PROTOCOL, STANDARD_FIELDS, EXTRA_FIELDS
from hp_ctl.uart import UartReceiver

logger = logging.getLogger(__name__)

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
        self.mqtt_client: Optional[MqttClient] = None
        self.uart_receiver: Optional[UartReceiver] = None
        self.ha_mapper = HomeAssistantMapper()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received (%d)", signum)
        self.shutdown()
        sys.exit(0)

    def _publish_discovery(self) -> None:
        """Publish Home Assistant discovery configs (once at startup)."""
        if self.mqtt_client:
            logger.info("Publishing Home Assistant discovery configs")
            # Publish configs for both standard and extra fields
            all_fields = STANDARD_FIELDS + EXTRA_FIELDS
            discovery_configs = self.ha_mapper.message_to_ha_discovery(all_fields)
            for topic, payload in discovery_configs.items():
                self.mqtt_client.publish(topic, payload)
            logger.info("Published %d discovery configs", len(discovery_configs))

    def _on_uart_message(self, raw_msg: bytes) -> None:
        """Callback invoked when UART receives a valid message.

        Args:
            raw_msg: Raw validated message bytes from UART.
        """
        try:
            # Decode message
            message = PROTOCOL.decode(raw_msg)

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
                # Initialize MQTT
                mqtt_config = self.config["mqtt"]
                self.mqtt_client = MqttClient(
                    broker=mqtt_config["broker"],
                    port=mqtt_config["port"],
                )
                self.mqtt_client.connect()
                logger.info("MQTT client connected")

                # Publish Home Assistant discovery configs once at startup
                self._publish_discovery()

                # Initialize UART with callback
                uart_config = self.config["uart"]
                self.uart_receiver = UartReceiver(
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
        if self.uart_receiver:
            self.uart_receiver.close()
        if self.mqtt_client:
            self.mqtt_client.disconnect()
        logger.info("Application shutdown complete")


def main() -> None:
    """Entry point for the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("hp_ctl.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    app = Application(config_path="config.yaml")
    app.run()


if __name__ == "__main__":
    main()









