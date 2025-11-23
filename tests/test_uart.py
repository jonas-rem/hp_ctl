import time
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from hp_ctl.uart import UartReceiver


def load_test_case(name: str) -> bytes:
    """Load raw hex from decoder test cases."""
    fixture_path = Path(__file__).parent / "fixtures" / "decoder_test_cases.yaml"
    with open(fixture_path, "r") as f:
        data = yaml.safe_load(f)
    raw_hex = data["test_cases"][name]["raw_hex"].replace(" ", "").replace("\n", "")
    return bytes.fromhex(raw_hex)


def test_uart_receiver_callback(mocker):
    """Test that UART receiver calls callback with mocked raw bytes."""
    test_message = load_test_case("panasonic_answer")

    mock_serial = MagicMock()
    # Make read() return bytes sequentially from the test message
    # Each call to read(n) returns the next n bytes
    read_position = [0]  # Use list to allow modification in nested function

    def mock_read(n):
        start = read_position[0]
        end = start + n
        result = test_message[start:end]
        read_position[0] = end
        return result

    mock_serial.read.side_effect = mock_read
    mocker.patch("serial.Serial", return_value=mock_serial)

    callback_called = []
    def mock_callback(message: bytes):
        callback_called.append(message)

    # Thread starts automatically in __init__ with poll_interval
    receiver = UartReceiver(
        port="/dev/ttyUSB0",
        baudrate=9600,
        on_message=mock_callback,
        poll_interval=0.01,
    )
    time.sleep(0.05)  # Allow loop to trigger
    receiver.close()

    # Assert callback was called with the raw bytes
    assert len(callback_called) > 0
    assert callback_called[0] == test_message


def test_uart_validate_length(mocker):
    """Test that UART receiver validates message length correctly."""
    mock_serial = MagicMock()
    # Return empty bytes so thread doesn't block
    mock_serial.read.return_value = b""
    mocker.patch("serial.Serial", return_value=mock_serial)

    receiver = UartReceiver(port="/dev/ttyUSB0", baudrate=9600)

    # Valid messages
    valid_msg = load_test_case("panasonic_answer")
    assert receiver.validate_length(valid_msg) is True

    valid_msg = load_test_case("my_panasonic_answer")
    assert receiver.validate_length(valid_msg) is True

    # Too short
    too_short = b"\x71\xc8"
    assert receiver.validate_length(too_short) is False

    # Length mismatch
    length_mismatch = load_test_case("invalid_message_length_mismatch")
    assert receiver.validate_length(length_mismatch) is False

    receiver.close()


def test_uart_validate_crc(mocker):
    """Test that UART receiver validates checksum correctly."""
    mock_serial = MagicMock()
    # Return empty bytes so thread doesn't block
    mock_serial.read.return_value = b""
    mocker.patch("serial.Serial", return_value=mock_serial)

    receiver = UartReceiver(port="/dev/ttyUSB0", baudrate=9600)

    # Valid messages
    valid_msg = load_test_case("panasonic_answer")
    assert receiver.validate_crc(valid_msg) is True

    valid_msg = load_test_case("my_panasonic_answer")
    assert receiver.validate_crc(valid_msg) is True

    # Invalid checksum
    invalid_checksum = load_test_case("invalid_checksum")
    assert receiver.validate_crc(invalid_checksum) is False

    receiver.close()
