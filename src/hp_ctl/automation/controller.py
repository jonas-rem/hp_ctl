# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Main automation controller orchestrating weather, storage, and energy tracking."""

import logging
from copy import deepcopy
from datetime import datetime, timedelta
from threading import Event, Thread
from typing import Any, Callable, Optional

from hp_ctl.automation.algorithm import AutomationAction, HeatingAlgorithm
from hp_ctl.automation.config import get_heat_demand_for_temp, validate_automation_config
from hp_ctl.automation.discovery import AutomationDiscovery
from hp_ctl.automation.storage import AutomationStorage, HeatPumpSnapshot
from hp_ctl.automation.weather import WeatherAPIClient, WeatherData
from hp_ctl.homeassistant import HomeAssistantMapper
from hp_ctl.mqtt import MqttClient

logger = logging.getLogger(__name__)


class AutomationController:
    """Main controller for automation features."""

    def __init__(
        self,
        config: dict[str, Any],
        mqtt_client: MqttClient,
        ha_mapper: HomeAssistantMapper,
        command_callback: Optional[Callable[[str, Any], None]] = None,
    ) -> None:
        """Initialize automation controller.

        Always initializes for data collection. Automatic control can be
        enabled/disabled at runtime via MQTT.

        Args:
            config: Automation configuration dictionary.
            mqtt_client: MQTT client instance (shared with main app).
            ha_mapper: Home Assistant mapper for discovery.
            command_callback: Callback to send commands back to heat pump.
        """
        # Validate config
        validate_automation_config(config)

        self.config = config
        self.mqtt_client = mqtt_client
        self.ha_mapper = ha_mapper
        self.device_id = ha_mapper.device_id
        self.command_callback = command_callback

        # Initialize discovery helper for automation entities
        self.discovery = AutomationDiscovery(
            device_id=self.device_id,
            device_name=ha_mapper.device_name,
            topic_prefix=ha_mapper.topic_prefix,
        )

        # Automatic control mode (toggleable at runtime via MQTT)
        # Data collection always runs, but automatic HP control respects this flag
        self.automatic_mode_enabled = config.get("enabled", False)

        # Initialize storage (always - needed for data collection)
        storage_config = config["storage"]
        self.storage = AutomationStorage(db_path=storage_config["db_path"])
        self.retention_days = storage_config["retention_days"]

        # Initialize algorithm
        self.algorithm = HeatingAlgorithm(config)

        # Initialize weather client (always - needed for data collection)
        weather_config = config["weather"]
        self.weather_client = WeatherAPIClient(
            latitude=weather_config["latitude"],
            longitude=weather_config["longitude"],
            on_data=self._on_weather_data,
            on_error=self._on_weather_error,
        )

        # Heat demand mapping
        self.heat_demand_map = config["heat_demand_map"]

        # Track current state
        self.current_snapshot = HeatPumpSnapshot(timestamp=datetime.now())
        self.last_inserted_snapshot: Optional[HeatPumpSnapshot] = None
        self.last_weather_update: Optional[datetime] = None
        self.last_cleanup: Optional[datetime] = None
        self.last_action = AutomationAction()

        # Cache for daily summary to avoid expensive recalculation on every MQTT message
        self._cached_daily_summary: Optional[Any] = None
        self._cached_summary_date: Optional[str] = None

        # Control loop thread
        self._control_thread: Optional[Thread] = None
        self._stop_event = Event()

        # Error state
        self.automation_paused = False
        self.last_error: Optional[str] = None

        # EEPROM protection: track command history per parameter
        # Limits to 10 changes per hour per parameter to prevent EEPROM wear
        self.change_history: dict[str, list[datetime]] = {}
        self.max_changes_per_hour = 10  # Hardcoded limit

        logger.info(
            "Automation controller initialized (automatic mode: %s, EEPROM limit: %d/hour)",
            "enabled" if self.automatic_mode_enabled else "disabled",
            self.max_changes_per_hour,
        )

    def start(self) -> None:
        """Start automation controller.

        Always starts data collection. Automatic control respects the
        automatic_mode_enabled flag.
        """
        logger.info(
            "Starting automation controller (automatic mode: %s)",
            "enabled" if self.automatic_mode_enabled else "disabled",
        )

        # Subscribe to heat pump state topics (for data collection)
        state_topics = [
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/outdoor_temp",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/heat_power_generation",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/heat_power_consumption",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/inlet_water_temp",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/outlet_water_temp",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/zone1_actual_temp",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/three_way_valve",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/hp_status",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/operating_mode",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/zone1_heat_target_temp",
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/dhw_target_temp",
        ]

        for topic in state_topics:
            self.mqtt_client.subscribe(topic)
            logger.debug("Subscribed to %s", topic)

        # Subscribe to automation control command topics
        self.mqtt_client.subscribe(
            f"{self.ha_mapper.topic_prefix}/{self.device_id}/automation/mode/set"
        )

        # Register message listener with topic filter
        topic_filter = f"{self.ha_mapper.topic_prefix}/{self.device_id}/#"
        self.mqtt_client.add_message_listener(self._on_message_received, topic_filter=topic_filter)
        logger.debug("Registered automation listener for: %s", topic_filter)

        # Publish Home Assistant discovery for automation
        self.publish_discovery()

        # Start weather fetching
        self.weather_client.start()

        # Start control loop thread
        self._stop_event.clear()
        self._control_thread = Thread(
            target=self._control_loop, daemon=True, name="Automation-Control"
        )
        self._control_thread.start()

        # Publish initial automation mode and status
        self._publish_automation_mode()
        self._publish_status()

        logger.info("Automation controller started")

    def stop(self) -> None:
        """Stop automation controller."""
        logger.info("Stopping automation controller")

        # Stop control loop
        self._stop_event.set()
        if self._control_thread:
            self._control_thread.join(timeout=5)

        # Stop weather client
        self.weather_client.stop()

        # Close database
        self.storage.close()

        logger.info("Automation controller stopped")

    def _on_message_received(self, topic: str, payload: str) -> None:
        """Handle incoming MQTT messages."""
        if topic.endswith("/automation/mode/set"):
            self._on_automation_mode_command(topic, payload)
        elif f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/" in topic:
            self._on_mqtt_state_message(topic, payload)

    def _on_automation_mode_command(self, topic: str, payload: str) -> None:
        """Handle automation mode change command from MQTT."""
        payload_lower = payload.strip().lower()

        if payload_lower == "automatic":
            self.automatic_mode_enabled = True
            logger.info("Automation mode: AUTOMATIC (will control heat pump)")
        elif payload_lower == "manual":
            self.automatic_mode_enabled = False
            logger.info("Automation mode: MANUAL (data collection only)")
        else:
            logger.warning("Invalid automation mode command: %s", payload)
            return

        # Publish updated status
        self._publish_automation_mode()
        self._publish_status()

    def _on_mqtt_state_message(self, topic: str, payload: str) -> None:
        """Handle incoming state messages from heat pump.

        Args:
            topic: MQTT topic.
            payload: Message payload (string).
        """
        if self.automation_paused:
            return  # Don't process messages while paused

        # Extract field name from topic
        # Format: hp_ctl/{device_id}/state/{field_name}
        if not topic.startswith(f"{self.ha_mapper.topic_prefix}/{self.device_id}/state/"):
            return

        field_name = topic.split("/")[-1]

        try:
            # Update current snapshot based on field
            if field_name == "outdoor_temp":
                self.current_snapshot.outdoor_temp = float(payload)
            elif field_name == "heat_power_generation":
                self.current_snapshot.heat_power_generation = float(payload)
            elif field_name == "heat_power_consumption":
                self.current_snapshot.heat_power_consumption = float(payload)
            elif field_name == "inlet_water_temp":
                self.current_snapshot.inlet_water_temp = float(payload)
            elif field_name == "outlet_water_temp":
                self.current_snapshot.outlet_water_temp = float(payload)
            elif field_name == "zone1_actual_temp":
                self.current_snapshot.zone1_actual_temp = float(payload)
            elif field_name == "three_way_valve":
                # Parse valve state from combined string: "Valve:Room, Defrost:Inactive"
                if "Valve:DHW" in payload:
                    self.current_snapshot.three_way_valve = "DHW"
                elif "Valve:Room" in payload:
                    self.current_snapshot.three_way_valve = "Room"
                else:
                    self.current_snapshot.three_way_valve = "Unknown"
            elif field_name == "hp_status":
                self.current_snapshot.hp_status = payload
            elif field_name == "operating_mode":
                self.current_snapshot.operating_mode = payload
            elif field_name == "zone1_heat_target_temp":
                self.current_snapshot.zone1_heat_target_temp = float(payload)
            elif field_name == "dhw_target_temp":
                self.current_snapshot.dhw_target_temp = float(payload)

            # Update timestamp
            self.current_snapshot.timestamp = datetime.now()

            # Store snapshot to database only if data has changed
            if self._snapshot_has_changed():
                self.storage.insert_snapshot(self.current_snapshot)
                # Deep copy to avoid reference issues
                self.last_inserted_snapshot = deepcopy(self.current_snapshot)
                # Invalidate daily summary cache since we inserted new data
                self._cached_daily_summary = None
                logger.debug("Snapshot inserted (data changed)")
            else:
                logger.debug("Snapshot skipped (no change)")

            # Update status (includes today's totals)
            self._publish_status()

            # Periodic cleanup (once per day)
            self._maybe_cleanup_old_data()

        except (ValueError, TypeError) as e:
            logger.warning("Failed to parse %s=%s: %s", field_name, payload, e)

    def _on_weather_data(self, weather_data: WeatherData) -> None:
        """Callback when new weather data is received.

        Args:
            weather_data: Weather data from API (24h average from previous day).
        """
        logger.info(
            "Weather data received: %.1f°C (24h avg for %s)",
            weather_data.outdoor_temp_avg_24h,
            weather_data.date,
        )

        # Update outdoor temp in current snapshot with the 24h average
        self.current_snapshot.outdoor_temp = weather_data.outdoor_temp_avg_24h
        self.last_weather_update = weather_data.timestamp

        # Clear error state if we were paused
        if self.automation_paused:
            self.automation_paused = False
            self.last_error = None
            logger.info("Automation resumed after weather API recovery")

        # Publish weather data to MQTT
        weather_topic = f"{self.device_id}/automation/weather"
        weather_payload = {
            "outdoor_temp_avg_24h": weather_data.outdoor_temp_avg_24h,
            "date": weather_data.date,
            "timestamp": weather_data.timestamp.isoformat(),
        }
        self.mqtt_client.publish(weather_topic, weather_payload)

        # Calculate estimated daily demand based on 24h average
        estimated_demand = get_heat_demand_for_temp(
            self.heat_demand_map, weather_data.outdoor_temp_avg_24h
        )
        logger.debug("Estimated daily heat demand: %.1f kWh", estimated_demand)

        # Publish automation status
        self._publish_status()

    def _on_weather_error(self, error_msg: str) -> None:
        """Callback when weather API error occurs.

        Args:
            error_msg: Error message description.
        """
        logger.error("Weather API error: %s", error_msg)

        # Pause automation
        self.automation_paused = True
        self.last_error = error_msg

        # Publish error to MQTT
        error_topic = f"{self.device_id}/automation/error"
        self.mqtt_client.publish(error_topic, error_msg)

        # Publish updated status
        self._publish_status()

    def _maybe_cleanup_old_data(self) -> None:
        """Perform periodic cleanup of old data (once per day)."""
        now = datetime.now()

        # Check if we've cleaned up today
        if self.last_cleanup is not None:
            time_since_cleanup = now - self.last_cleanup
            if time_since_cleanup < timedelta(days=1):
                return

        # Perform cleanup
        logger.info("Running database cleanup (retention: %d days)", self.retention_days)
        deleted = self.storage.cleanup_old_data(self.retention_days)
        self.last_cleanup = now

        logger.info("Cleanup complete: deleted %d old records", deleted)

    def _snapshot_has_changed(self) -> bool:
        """Check if current snapshot has changed compared to last inserted snapshot.

        Compares only the persisted fields (excludes timestamp and three_way_valve).

        Returns:
            True if snapshot has changed or is first snapshot, False otherwise.
        """
        if self.last_inserted_snapshot is None:
            return True  # First snapshot - always insert

        last = self.last_inserted_snapshot
        curr = self.current_snapshot

        # Compare all persisted fields
        return (
            curr.outdoor_temp != last.outdoor_temp
            or curr.heat_power_generation != last.heat_power_generation
            or curr.heat_power_consumption != last.heat_power_consumption
            or curr.inlet_water_temp != last.inlet_water_temp
            or curr.outlet_water_temp != last.outlet_water_temp
            or curr.zone1_actual_temp != last.zone1_actual_temp
            or curr.dhw_target_temp != last.dhw_target_temp
            or curr.zone1_heat_target_temp != last.zone1_heat_target_temp
            or curr.hp_status != last.hp_status
            or curr.operating_mode != last.operating_mode
        )

    def _get_cached_daily_summary(self) -> Optional[Any]:
        """Get today's daily summary with caching to avoid expensive recalculation.

        The summary is cached and only recalculated when:
        - Cache is empty
        - Date has changed (new day)
        - New data was inserted to database

        Returns:
            DailySummary instance or None if no data available.
        """
        today = datetime.now()
        today_str = today.date().isoformat()

        # Check if we need to recalculate
        if self._cached_daily_summary is None or self._cached_summary_date != today_str:
            # Recalculate and cache
            self._cached_daily_summary = self.storage.get_daily_summary(today)
            self._cached_summary_date = today_str
            logger.debug("Daily summary recalculated and cached")

        return self._cached_daily_summary

    def publish_discovery(self) -> None:
        """Publish Home Assistant discovery configs for automation entities."""
        logger.info("Publishing Home Assistant discovery configs for automation")
        discovery_configs = self.discovery.get_discovery_configs()
        for topic, payload in discovery_configs.items():
            self.mqtt_client.publish(topic, payload)

    def _can_send_command(self, param_name: str) -> bool:
        """Check if we can send command without exceeding EEPROM write limit.

        Allows max 10 changes per hour per parameter to prevent EEPROM wear.
        Uses rolling window: old changes (>1 hour) are automatically expired.

        Args:
            param_name: Name of parameter to check (e.g., 'hp_status').

        Returns:
            True if command can be sent, False if limit exceeded.
        """
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # Get change history for this parameter
        if param_name not in self.change_history:
            self.change_history[param_name] = []

        history = self.change_history[param_name]

        # Remove changes older than 1 hour (rolling window)
        history[:] = [ts for ts in history if ts > one_hour_ago]

        # Check if we've hit the limit
        if len(history) >= self.max_changes_per_hour:
            logger.warning(
                "EEPROM protection: %s change limit reached (%d in last hour), suppressing command",
                param_name,
                len(history),
            )
            return False

        return True

    def _record_command_sent(self, param_name: str) -> None:
        """Record that a command was sent (for EEPROM protection tracking).

        Args:
            param_name: Name of parameter that was changed.
        """
        now = datetime.now()
        if param_name not in self.change_history:
            self.change_history[param_name] = []
        self.change_history[param_name].append(now)
        logger.debug(
            "EEPROM protection: recorded %s change (%d in last hour)",
            param_name,
            len(self.change_history[param_name]),
        )

    def _control_loop(self) -> None:
        """Background loop for active heat pump control (runs every 1 min)."""
        logger.info("Automation control loop started (interval: 1 min)")

        while not self._stop_event.wait(timeout=60):  # 1 minute
            if not self.automatic_mode_enabled or self.automation_paused:
                continue

            try:
                self._run_control_logic()
            except Exception as e:
                logger.exception("Error in automation control logic: %s", e)

    def _run_control_logic(self) -> None:
        """Execute the heating algorithm and send commands."""
        # 1. Gather inputs
        now = datetime.now()
        summary = self._get_cached_daily_summary()
        actual_heat = summary.total_heat_kwh if summary else 0.0

        last_weather = self.weather_client.get_last_data()
        outdoor_avg = (
            last_weather.outdoor_temp_avg_24h
            if last_weather
            else self.current_snapshot.outdoor_temp
        )

        if outdoor_avg is None:
            logger.warning("Control loop: No outdoor temperature data skipping")
            return

        demand = get_heat_demand_for_temp(self.heat_demand_map, outdoor_avg)

        # 2. Call algorithm
        action = self.algorithm.decide(
            current_time=now,
            outdoor_temp_avg_24h=outdoor_avg,
            actual_heat_kwh_today=actual_heat,
            estimated_demand_kwh=demand,
            current_outlet_temp=self.current_snapshot.outlet_water_temp or 0.0,
            current_inlet_temp=self.current_snapshot.inlet_water_temp or 0.0,
            zone1_actual_temp=self.current_snapshot.zone1_actual_temp or 0.0,
            current_hp_status=self.current_snapshot.hp_status or "Off",
            current_operating_mode=self.current_snapshot.operating_mode or "Heat",
            three_way_valve=self.current_snapshot.three_way_valve or "Room",
            heat_power_generation=self.current_snapshot.heat_power_generation or 0.0,
            heat_power_consumption=self.current_snapshot.heat_power_consumption or 0.0,
        )
        self.last_action = action

        logger.debug("Automation decision: %s (Reason: %s)", action, action.reason)

        # 3. Execute actions WITH EEPROM PROTECTION
        if self.command_callback:
            # HP Status
            if action.hp_status and action.hp_status != self.current_snapshot.hp_status:
                if self._can_send_command("hp_status"):
                    self.command_callback("hp_status", action.hp_status)
                    self._record_command_sent("hp_status")
                    logger.info("Sent automation command: hp_status = %s", action.hp_status)

            # Operating Mode
            if (
                action.operating_mode
                and action.operating_mode != self.current_snapshot.operating_mode
            ):
                if self._can_send_command("operating_mode"):
                    self.command_callback("operating_mode", action.operating_mode)
                    self._record_command_sent("operating_mode")
                    logger.info(
                        "Sent automation command: operating_mode = %s", action.operating_mode
                    )

            # DHW Target Temp
            if (
                action.dhw_target_temp is not None
                and action.dhw_target_temp != self.current_snapshot.dhw_target_temp
            ):
                if self._can_send_command("dhw_target_temp"):
                    self.command_callback("dhw_target_temp", action.dhw_target_temp)
                    self._record_command_sent("dhw_target_temp")
                    logger.info(
                        "Sent automation command: dhw_target_temp = %d", action.dhw_target_temp
                    )

            # Zone1 Heat Target Temp
            if (
                action.target_temp is not None
                and action.target_temp != self.current_snapshot.zone1_heat_target_temp
            ):
                # We only send target_temp if HP is On
                is_on = (action.hp_status == "On") or (
                    action.hp_status is None and self.current_snapshot.hp_status == "On"
                )
                if is_on and self._can_send_command("zone1_heat_target_temp"):
                    self.command_callback("zone1_heat_target_temp", action.target_temp)
                    self._record_command_sent("zone1_heat_target_temp")
                    logger.info(
                        "Sent automation command: zone1_heat_target_temp = %d", action.target_temp
                    )

        # 4. Publish active target for monitoring
        self._publish_status()

    def _publish_automation_mode(self) -> None:
        """Publish current automation mode to MQTT."""
        mode_topic = f"{self.device_id}/automation/mode"
        mode = "automatic" if self.automatic_mode_enabled else "manual"
        self.mqtt_client.publish(mode_topic, mode)
        logger.debug("Published automation mode: %s", mode)

    def _publish_individual_sensors(self, status: dict[str, Any]) -> None:
        """Publish individual topics for HA sensors.

        Args:
            status: Automation status dictionary.
        """
        base = f"{self.device_id}/automation"

        # Weather & Demand
        if status.get("outdoor_temp_avg_24h") is not None:
            self.mqtt_client.publish(
                f"{base}/outdoor_temp_avg_24h", str(status["outdoor_temp_avg_24h"])
            )
        if status.get("weather_date"):
            self.mqtt_client.publish(f"{base}/weather_date", status["weather_date"])
        if status.get("estimated_daily_demand_kwh") is not None:
            self.mqtt_client.publish(
                f"{base}/estimated_daily_demand",
                str(status["estimated_daily_demand_kwh"]),
            )
        if status.get("active_target_temp") is not None:
            self.mqtt_client.publish(
                f"{base}/active_target_temp", str(status["active_target_temp"])
            )
        if status.get("reason"):
            self.mqtt_client.publish(f"{base}/reason", status["reason"])

        # Today's data
        if "today" in status:
            today = status["today"]
            for key in [
                "total_heat_kwh",
                "total_consumption_kwh",
                "avg_cop",
                "runtime_hours",
            ]:
                if today.get(key) is not None:
                    self.mqtt_client.publish(f"{base}/today/{key}", str(today[key]))

    def _publish_status(self) -> None:
        """Publish automation status to MQTT."""
        # Get today's daily summary (cached to avoid expensive recalculation)
        daily_summary = self._get_cached_daily_summary()

        # Get yesterday's 24h average outdoor temp from weather data
        outdoor_temp_avg_24h = None
        weather_date = None
        last_weather = self.weather_client.get_last_data()
        if last_weather:
            outdoor_temp_avg_24h = last_weather.outdoor_temp_avg_24h
            weather_date = last_weather.date
        elif self.current_snapshot.outdoor_temp is not None:
            # Fallback to snapshot data if weather not yet fetched
            outdoor_temp_avg_24h = self.current_snapshot.outdoor_temp

        # Calculate estimated demand if we have outdoor temp
        estimated_demand = None
        if outdoor_temp_avg_24h is not None:
            estimated_demand = get_heat_demand_for_temp(self.heat_demand_map, outdoor_temp_avg_24h)

        # Build status payload
        status: dict[str, Any] = {
            "mode": "automatic" if self.automatic_mode_enabled else "manual",
            "paused": self.automation_paused,
            "last_error": self.last_error,
            "outdoor_temp_avg_24h": outdoor_temp_avg_24h,
            "weather_date": weather_date,  # Which day this average represents
            "estimated_daily_demand_kwh": estimated_demand,
            "active_target_temp": self.last_action.target_temp,
            "reason": self.last_action.reason,
            "db_snapshot_count": self.storage.get_snapshot_count(),
            "last_weather_update": (
                self.last_weather_update.isoformat() if self.last_weather_update else None
            ),
        }

        # Add today's summary if available
        if daily_summary:
            status["today"] = {
                "total_heat_kwh": round(daily_summary.total_heat_kwh, 2),
                "total_consumption_kwh": round(daily_summary.total_consumption_kwh, 2),
                "avg_cop": round(daily_summary.avg_cop, 2),
                "runtime_hours": round(daily_summary.runtime_hours, 2),
            }

        # Publish to MQTT
        status_topic = f"{self.device_id}/automation/status"
        self.mqtt_client.publish(status_topic, status)

        # Publish individual topics for HA sensors
        self._publish_individual_sensors(status)

        logger.debug("Published automation status")

    def publish_daily_summary(self, date: Optional[datetime] = None) -> None:
        """Manually publish daily summary for a given date.

        Args:
            date: Date to publish summary for (defaults to yesterday).
        """
        if date is None:
            # Default to yesterday (complete day)
            date = datetime.now() - timedelta(days=1)

        summary = self.storage.get_daily_summary(date)
        if summary is None:
            logger.warning("No data available for %s", date.date())
            return

        # Publish to MQTT
        summary_topic = f"{self.device_id}/automation/energy/daily"
        summary_payload = {
            "date": summary.date,
            "total_heat_kwh": round(summary.total_heat_kwh, 2),
            "total_consumption_kwh": round(summary.total_consumption_kwh, 2),
            "avg_cop": round(summary.avg_cop, 2),
            "avg_outdoor_temp": round(summary.avg_outdoor_temp, 1),
            "runtime_hours": round(summary.runtime_hours, 2),
        }

        self.mqtt_client.publish(summary_topic, summary_payload)
        logger.info("Published daily summary for %s", summary.date)
