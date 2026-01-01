# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Weather API client using Open-Meteo service."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Thread
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# Open-Meteo API endpoint (historical data)
OPEN_METEO_API = "https://api.open-meteo.com/v1/forecast"


@dataclass
class WeatherData:
    """Weather data from API."""

    timestamp: datetime
    outdoor_temp_avg_24h: float  # °C - 24h average from previous day
    date: str  # Date this average represents (YYYY-MM-DD)
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

        Fetches 24h average temperature on startup and at midnight (00:00) daily.

        Args:
            latitude: Location latitude.
            longitude: Location longitude.
            on_data: Callback invoked when new weather data is received.
            on_error: Callback invoked when API error occurs.
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
            "Starting weather client (lat=%.2f, lon=%.2f, "
            "fetches at midnight)",
            self.latitude,
            self.longitude,
        )

        self._stop_event.clear()
        self._thread = Thread(
            target=self._fetch_loop, daemon=True, name="Weather-Fetcher"
        )
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

        Fetches immediately on startup, then schedules next fetch for midnight (00:00).
        """
        # Fetch immediately on startup
        try:
            weather_data = self._fetch_weather()

            if weather_data:
                self._last_data = weather_data
                logger.info(
                    "Weather updated: %.1f°C (24h avg for %s)",
                    weather_data.outdoor_temp_avg_24h,
                    weather_data.date,
                )

                # Invoke callback
                if self.on_data_callback:
                    self.on_data_callback(weather_data)

        except Exception as e:  # pylint: disable=broad-except
            error_msg = f"Failed to fetch weather on startup: {e}"
            logger.exception(error_msg)

            # Invoke error callback
            if self.on_error_callback:
                self.on_error_callback(error_msg)

        # Continue fetching at midnight each day
        while not self._stop_event.is_set():
            # Calculate seconds until next midnight
            now = datetime.now()
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            seconds_until_midnight = (tomorrow - now).total_seconds()

            logger.debug(
                "Next weather fetch in %.1f hours (at midnight)", seconds_until_midnight / 3600
            )

            # Wait until midnight (or stop event)
            if self._stop_event.wait(timeout=seconds_until_midnight):
                break  # Stop event was set

            # Fetch at midnight
            try:
                weather_data = self._fetch_weather()

                if weather_data:
                    self._last_data = weather_data
                    logger.info(
                        "Weather updated: %.1f°C (24h avg for %s)",
                        weather_data.outdoor_temp_avg_24h,
                        weather_data.date,
                    )

                    # Invoke callback
                    if self.on_data_callback:
                        self.on_data_callback(weather_data)

            except Exception as e:  # pylint: disable=broad-except
                error_msg = f"Failed to fetch weather: {e}"
                logger.exception(error_msg)

                # Invoke error callback
                if self.on_error_callback:
                    self.on_error_callback(error_msg)

    def _fetch_weather(self) -> Optional[WeatherData]:
        """Fetch 24-hour average temperature for yesterday from Open-Meteo API.

        Returns:
            WeatherData instance with yesterday's 24h average temp, or None on failure.
        """
        # Calculate yesterday's date
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")

        params: dict[str, str | float] = {
            "latitude": str(self.latitude),
            "longitude": str(self.longitude),
            "start_date": yesterday_str,
            "end_date": yesterday_str,
            "daily": "temperature_2m_mean",  # Daily mean temperature
            "timezone": "auto",
        }

        logger.debug("Fetching 24h average temperature for %s", yesterday_str)
        response = requests.get(OPEN_METEO_API, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Extract daily mean temperature
        if "daily" not in data or "temperature_2m_mean" not in data["daily"]:
            logger.warning("Unexpected API response format: %s", data)
            return None

        temp_values = data["daily"]["temperature_2m_mean"]
        if not temp_values or len(temp_values) == 0:
            logger.warning("No temperature data available for %s", yesterday_str)
            return None

        outdoor_temp_avg = float(temp_values[0])
        timestamp = datetime.now()

        return WeatherData(
            timestamp=timestamp,
            outdoor_temp_avg_24h=outdoor_temp_avg,
            date=yesterday_str,
        )
