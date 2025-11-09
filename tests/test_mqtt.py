import json
from unittest.mock import MagicMock

import pytest

from hp_ctl.mqtt import MqttClient


@pytest.fixture
def mqtt_broker(mocker):
    """Mock MQTT broker for testing."""
    mock_client = MagicMock()
    mocker.patch("paho.mqtt.client.Client", return_value=mock_client)
    return mock_client


def test_mqtt_client_publish(mqtt_broker):
    """Test MQTT client publishes message correctly."""
    client = MqttClient(broker="localhost", port=1883, topic_prefix="test")

    payload = {"temperature": 25.5, "humidity": 60}
    client.publish("sensor/data", payload)

    # Verify publish was called with correct topic and JSON payload
    mqtt_broker.publish.assert_called_once()
    call_args = mqtt_broker.publish.call_args
    assert call_args[0][0] == "test/sensor/data"
    assert json.loads(call_args[0][1]) == payload


def test_mqtt_client_connect(mqtt_broker):
    """Test MQTT client connects to broker."""
    client = MqttClient(broker="localhost", port=1883)
    client.connect()

    mqtt_broker.connect.assert_called_once_with("localhost", 1883, keepalive=60)
    mqtt_broker.loop_start.assert_called_once()


def test_mqtt_client_disconnect(mqtt_broker):
    """Test MQTT client disconnects from broker."""
    client = MqttClient(broker="localhost", port=1883)
    client.disconnect()

    mqtt_broker.loop_stop.assert_called_once()
    mqtt_broker.disconnect.assert_called_once()


def test_mqtt_client_on_connect_success(mqtt_broker):
    """Test on_connect callback with successful connection."""
    client = MqttClient(broker="localhost")
    client._on_connect(mqtt_broker, None, None, 0, None)

    assert client.connected is True


def test_mqtt_client_on_connect_failure(mqtt_broker):
    """Test on_connect callback with failed connection."""
    client = MqttClient(broker="localhost")
    client._on_connect(mqtt_broker, None, None, 1, None)

    assert client.connected is False
