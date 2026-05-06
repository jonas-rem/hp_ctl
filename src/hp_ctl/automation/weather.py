# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Weather API client using Open-Meteo service for forecast data."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Thread
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# Open-Meteo API endpoint
OPEN_METEO_API = "https://api.open-meteo.com/v1/forecast"

# Scheduled daily fetch time (00:15 to avoid API load at midnight)
FETCH_HOUR = 0
FETCH_MINUTE = 15

# Retry configuration for failed scheduled fetches
MAX_RETRY_ATTEMPTS = 3
RETRY_INTERVAL_S = 30 * 60  # 30 minutes between retries


@dataclass
class WeatherData:
    """Weather data from API."""

    timestamp: datetime
    outdoor_temp_forecast_24h: float  # °C - forecasted 24h average for today
    date: str  # Date this forecast represents (YYYY-MM-DD)
    source: str = "open-meteo"


class WeatherAPIClient:
    """Client for fetching weather data from Open-Meteo API."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        on_data: Optional[Callable[[WeatherData], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize weather API client.

        Fetches 24h average temperature on startup and at 00:15 daily.
        On failure, retries up to MAX_RETRY_ATTEMPTS times at RETRY_INTERVAL_S
        intervals before invoking the error callback.

        Args:
            latitude: Location latitude.
            longitude: Location longitude.
            on_data: Callback invoked when new weather data is received.
            on_error: Callback invoked when all fetch attempts are exhausted.
        """
        self.latitude = latitude
        self.longitude = longitude
        self.on_data_callback = on_data
        self.on_error_callback = on_error

        self._thread: Optional[Thread] = None
        self._stop_event = Event()
        self._last_data: Optional[WeatherData] = None

    def start(self) -> None:
        """Start periodic weather fetching in background thread."""
        if self._thread is not None:
            logger.warning("Weather client already started")
            return

        logger.info(
            "Starting weather client (lat=%.2f, lon=%.2f, fetches at %02d:%02d)",
            self.latitude,
            self.longitude,
            FETCH_HOUR,
            FETCH_MINUTE,
        )

        self._stop_event.clear()
        self._thread = Thread(target=self._fetch_loop, daemon=True, name="Weather-Fetcher")
        self._thread.start()

    def stop(self) -> None:
        """Stop weather fetching thread."""
        if self._thread is None:
            return

        logger.info("Stopping weather client")
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None

    def get_last_data(self) -> Optional[WeatherData]:
        """Get the most recently fetched weather data.

        Returns:
            Last WeatherData or None if no data fetched yet.
        """
        return self._last_data

    def _fetch_loop(self) -> None:
        """Background thread loop for periodic weather fetching.

        Fetches immediately on startup, then schedules next fetch for 00:15.
        On failure, retries up to MAX_RETRY_ATTEMPTS times before invoking
        the error callback.
        """
        # Fetch immediately on startup; notify error callback if it fails
        # (no retries on startup — controller will pause if no data available)
        success = self._update_and_notify("startup")
        if not success and self.on_error_callback:
            self.on_error_callback("Weather fetch failed on startup")

        # Continue fetching at 00:15 each day
        while not self._stop_event.is_set():
            s_to_next = self._get_s_to_scheduled_fetch()

            logger.debug(
                "Next weather fetch in %.1f hours (at %02d:%02d)",
                s_to_next / 3600,
                FETCH_HOUR,
                FETCH_MINUTE,
            )

            # Wait until scheduled time (or stop event)
            if self._stop_event.wait(timeout=s_to_next):
                break  # Stop event was set

            # First attempt at scheduled time
            success = self._update_and_notify("scheduled")

            # On failure, retry with increasing attempt count
            attempt = 0
            while not success and attempt < MAX_RETRY_ATTEMPTS:
                attempt += 1
                logger.warning(
                    "Scheduled weather fetch failed, retrying in %.0f min (attempt %d/%d)",
                    RETRY_INTERVAL_S / 60,
                    attempt,
                    MAX_RETRY_ATTEMPTS,
                )
                if self._stop_event.wait(timeout=RETRY_INTERVAL_S):
                    return  # Stop event was set during retry wait

                success = self._update_and_notify(f"retry-{attempt}")

            if not success:
                # All retries exhausted — invoke error callback once
                error_msg = (
                    f"Weather fetch failed after {MAX_RETRY_ATTEMPTS + 1} attempts "
                    f"(scheduled + {MAX_RETRY_ATTEMPTS} retries)"
                )
                logger.error(error_msg)
                if self.on_error_callback:
                    self.on_error_callback(error_msg)

    def _get_s_to_scheduled_fetch(self) -> float:
        """Calculate seconds until next scheduled fetch at FETCH_HOUR:FETCH_MINUTE."""
        now = datetime.now()
        next_fetch = now.replace(
            hour=FETCH_HOUR, minute=FETCH_MINUTE, second=0, microsecond=0
        )
        if next_fetch <= now:
            next_fetch += timedelta(days=1)
        return (next_fetch - now).total_seconds()

    def _update_and_notify(self, reason: str) -> bool:
        """Fetch weather data and notify the data callback on success.

        Args:
            reason: Human-readable reason string for logging (e.g. "startup", "scheduled").

        Returns:
            True if data was successfully fetched and the callback invoked,
            False on any error (exception is logged but not re-raised).
        """
        try:
            weather_data = self._fetch_weather()

            if weather_data:
                self._last_data = weather_data
                logger.info(
                    "Weather updated (%s): %.1f°C (24h forecast for %s)",
                    reason,
                    weather_data.outdoor_temp_forecast_24h,
                    weather_data.date,
                )

                # Invoke callback
                if self.on_data_callback:
                    self.on_data_callback(weather_data)

                return True

            return False

        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Failed to fetch weather (%s): %s", reason, e)
            return False

    def _fetch_weather(self) -> Optional[WeatherData]:
        """Fetch forecasted 24-hour average temperature for today from Open-Meteo API.

        Called at 00:15, so "today" represents the next 24 hours.

        Returns:
            WeatherData instance with today's 24h forecast temp, or None on failure.
        """
        params: dict[str, str | int | float] = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "forecast_days": 1,  # today only
            "daily": "temperature_2m_mean",  # Daily mean temperature
            "timezone": "auto",
        }

        logger.debug("Fetching 24h average temperature forecast for today")
        response = requests.get(OPEN_METEO_API, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Extract daily mean temperature
        if "daily" not in data or "temperature_2m_mean" not in data["daily"]:
            logger.warning("Unexpected API response format: %s", data)
            return None

        temp_values = data["daily"]["temperature_2m_mean"]
        if not temp_values:
            logger.warning("Insufficient temperature data available")
            return None

        # forecast_days=1 returns [today] - at 00:15 this is the next 24 hours
        outdoor_temp_forecast = float(temp_values[0])
        today_str = data["daily"]["time"][0]

        return WeatherData(
            timestamp=datetime.now(),
            outdoor_temp_forecast_24h=outdoor_temp_forecast,
            date=today_str,
        )
