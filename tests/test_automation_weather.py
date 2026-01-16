# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Tests for automation weather module."""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from hp_ctl.automation.weather import WeatherAPIClient, WeatherData


@pytest.fixture
def mock_response():
    """Create a mock Open-Meteo API response for forecast."""
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "daily": {
            "time": [today],
            "temperature_2m_mean": [5.2],  # today
        }
    }


def test_weather_data_creation():
    """Test WeatherData dataclass creation."""
    now = datetime.now()
    data = WeatherData(
        timestamp=now,
        outdoor_temp_forecast_24h=5.2,
        date="2025-12-25",
    )

    assert data.timestamp == now
    assert data.outdoor_temp_forecast_24h == 5.2
    assert data.date == "2025-12-25"
    assert data.source == "open-meteo"


def test_weather_client_init():
    """Test WeatherAPIClient initialization."""
    client = WeatherAPIClient(
        latitude=52.52,
        longitude=13.41,
    )

    assert client.latitude == 52.52
    assert client.longitude == 13.41
    assert client.on_data_callback is None
    assert client.on_error_callback is None
    assert client._thread is None
    assert client.get_last_data() is None


def test_weather_client_with_callbacks():
    """Test WeatherAPIClient initialization with callbacks."""
    on_data = MagicMock()
    on_error = MagicMock()

    client = WeatherAPIClient(
        latitude=52.52,
        longitude=13.41,
        on_data=on_data,
        on_error=on_error,
    )

    assert client.on_data_callback == on_data
    assert client.on_error_callback == on_error


@patch("hp_ctl.automation.weather.requests.get")
def test_fetch_weather_success(mock_get, mock_response):
    """Test successful weather data fetching."""
    mock_get.return_value.json.return_value = mock_response
    mock_get.return_value.raise_for_status = MagicMock()

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)
    weather_data = client._fetch_weather()

    assert weather_data is not None
    assert weather_data.outdoor_temp_forecast_24h == 5.2
    assert isinstance(weather_data.timestamp, datetime)

    # Verify date is today (forecast for next 24 hours)
    today = datetime.now().strftime("%Y-%m-%d")
    assert weather_data.date == today

    # Verify API call
    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert call_args[0][0] == "https://api.open-meteo.com/v1/forecast"
    assert call_args[1]["params"]["latitude"] == 52.52
    assert call_args[1]["params"]["longitude"] == 13.41
    assert call_args[1]["params"]["forecast_days"] == 1
    assert call_args[1]["params"]["daily"] == "temperature_2m_mean"


@patch("hp_ctl.automation.weather.requests.get")
def test_fetch_weather_missing_data(mock_get):
    """Test weather fetch with missing data in response."""
    mock_get.return_value.json.return_value = {"daily": {}}
    mock_get.return_value.raise_for_status = MagicMock()

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)
    weather_data = client._fetch_weather()

    assert weather_data is None


@patch("hp_ctl.automation.weather.requests.get")
def test_fetch_weather_empty_values(mock_get):
    """Test weather fetch with empty temperature values."""
    mock_get.return_value.json.return_value = {
        "daily": {
            "time": [],
            "temperature_2m_mean": [],
        }
    }
    mock_get.return_value.raise_for_status = MagicMock()

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)
    weather_data = client._fetch_weather()

    assert weather_data is None


@patch("hp_ctl.automation.weather.requests.get")
def test_fetch_weather_insufficient_data(mock_get):
    """Test weather fetch with no temperature data."""
    mock_get.return_value.json.return_value = {
        "daily": {
            "time": [],
            "temperature_2m_mean": [],  # No data at all
        }
    }
    mock_get.return_value.raise_for_status = MagicMock()

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)
    weather_data = client._fetch_weather()

    assert weather_data is None


@patch("hp_ctl.automation.weather.requests.get")
def test_fetch_weather_api_error(mock_get):
    """Test weather fetch when API raises error."""
    mock_get.side_effect = Exception("API Error")

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)

    with pytest.raises(Exception, match="API Error"):
        client._fetch_weather()


@patch("hp_ctl.automation.weather.requests.get")
def test_weather_client_start_stop(mock_get, mock_response):
    """Test starting and stopping weather client."""
    mock_get.return_value.json.return_value = mock_response
    mock_get.return_value.raise_for_status = MagicMock()

    on_data = MagicMock()
    client = WeatherAPIClient(
        latitude=52.52,
        longitude=13.41,
        on_data=on_data,
    )

    # Start client
    client.start()
    assert client._thread is not None
    assert client._thread.is_alive()

    # Wait a bit for initial fetch
    time.sleep(0.5)

    # Verify callback was invoked
    assert on_data.call_count >= 1
    weather_data = on_data.call_args[0][0]
    assert isinstance(weather_data, WeatherData)
    assert weather_data.outdoor_temp_forecast_24h == 5.2

    # Verify last_data is set
    last_data = client.get_last_data()
    assert last_data is not None
    assert last_data.outdoor_temp_forecast_24h == 5.2

    # Stop client
    client.stop()
    time.sleep(0.2)
    # Thread is set to None after stop
    assert client._thread is None


@patch("hp_ctl.automation.weather.requests.get")
def test_weather_client_error_callback(mock_get):
    """Test error callback is invoked on fetch failure."""
    mock_get.side_effect = Exception("Network error")

    on_error = MagicMock()
    client = WeatherAPIClient(
        latitude=52.52,
        longitude=13.41,
        on_error=on_error,
    )

    # Start client (will fail on initial fetch)
    client.start()
    time.sleep(0.5)

    # Verify error callback was invoked
    assert on_error.call_count >= 1
    error_msg = on_error.call_args[0][0]
    assert "Network error" in error_msg

    client.stop()


@patch("hp_ctl.automation.weather.requests.get")
def test_weather_client_multiple_start(mock_get, mock_response):
    """Test that starting client multiple times doesn't create multiple threads."""
    mock_get.return_value.json.return_value = mock_response
    mock_get.return_value.raise_for_status = MagicMock()

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)

    client.start()
    first_thread = client._thread

    client.start()  # Should log warning but not create new thread
    assert client._thread == first_thread

    client.stop()


def test_weather_client_stop_without_start():
    """Test stopping client that was never started."""
    client = WeatherAPIClient(latitude=52.52, longitude=13.41)

    # Should not raise any errors
    client.stop()
    assert client._thread is None


@patch("hp_ctl.automation.weather.requests.get")
def test_fetch_weather_params(mock_get, mock_response):
    """Test that fetch uses correct parameters for forecast."""
    mock_get.return_value.json.return_value = mock_response
    mock_get.return_value.raise_for_status = MagicMock()

    client = WeatherAPIClient(latitude=52.52, longitude=13.41)
    client._fetch_weather()

    # Verify the API was called with forecast_days=1 (today only)
    call_args = mock_get.call_args[1]["params"]

    assert call_args["latitude"] == 52.52
    assert call_args["longitude"] == 13.41
    assert call_args["forecast_days"] == 1
    assert "past_days" not in call_args
    assert "start_date" not in call_args
    assert "end_date" not in call_args
