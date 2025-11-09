from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest
import yaml

from hp_ctl.protocol import MESSAGE_CODEC, Message


@dataclass
class MessageTestCase:
    """Test case combining raw message, expected decoded result, and description"""
    name: str
    raw_hex: str
    expected: Message
    expected_fields: set[str]  # Track which fields were explicitly specified
    should_raise: Optional[type] = None
    error_message: Optional[str] = None


def _load_test_cases() -> dict:
    """Load test cases from YAML fixture file"""
    fixture_path = (
        Path(__file__).parent / "fixtures" / "decoder_test_cases.yaml"
    )

    with open(fixture_path, "r") as f:
        data = yaml.safe_load(f)

    test_cases = {}
    for case_id, case_data in data["test_cases"].items():
        # Clean up raw_hex by removing whitespace and newlines
        raw_hex = case_data["raw_hex"].replace(" ", "").replace("\n", "")

        # Build expected Message with only specified fields
        expected_dict = case_data.get("expected", {})
        message_kwargs = {"fields": {}}

        for field_name, value in expected_dict.items():
            if field_name in ("len", "checksum"):
                # Message-level fields
                if field_name == "checksum" and isinstance(value, str):
                    message_kwargs[field_name] = bytes.fromhex(value)
                else:
                    message_kwargs[field_name] = value
            else:
                # Decoded fields go in fields dict
                message_kwargs["fields"][field_name] = value

        expected = Message(**message_kwargs)

        should_raise = None
        error_message = None
        if "should_raise" in case_data:
            should_raise_name = case_data["should_raise"]
            exception_map = {"ValueError": ValueError}
            should_raise = exception_map.get(should_raise_name)
            error_message = case_data.get("error_message")

        test_cases[case_id] = MessageTestCase(
            name=case_id,
            raw_hex=raw_hex,
            expected=expected,
            expected_fields=set(expected_dict.keys()),
            should_raise=should_raise,
            error_message=error_message,
        )

    return test_cases


TEST_CASES = _load_test_cases()


@pytest.fixture
def codec():
    return MESSAGE_CODEC


def _validate_message(decoded: Message, expected: Message, expected_fields: set[str]) -> None:
    """Validate decoded message against expected values.

    Only checks fields that were explicitly specified in the test case.
    """
    # Check message-level fields (len, checksum)
    for field_name in expected_fields:
        if field_name in ('len', 'checksum'):
            expected_value = getattr(expected, field_name)
            decoded_value = getattr(decoded, field_name)
            assert decoded_value == expected_value, (
                f"{field_name} mismatch: {decoded_value} != {expected_value}"
            )
        elif field_name in expected.fields:
            # Check decoded fields dict
            expected_value = expected.fields[field_name]
            decoded_value = decoded.fields.get(field_name)
            assert decoded_value == expected_value, (
                f"{field_name} mismatch: {decoded_value} != {expected_value}"
            )


@pytest.mark.parametrize("test_case", TEST_CASES.values(), ids=lambda tc: tc.name)
def test_decoder_parses_valid_message(codec, test_case):
    """Test that decoder can parse a valid UART message or raises expected errors."""
    raw_bytes = bytes.fromhex(test_case.raw_hex)

    if test_case.should_raise:
        with pytest.raises(test_case.should_raise) as exc_info:
            codec.decode(raw_bytes)
        if test_case.error_message:
            assert test_case.error_message in str(exc_info.value)
    else:
        message = codec.decode(raw_bytes)
        assert isinstance(message, Message)
        _validate_message(message, test_case.expected, test_case.expected_fields)

def test_temp_converter():
    from hp_ctl.protocol import temp_converter
    assert temp_converter(176) == 48
    assert temp_converter(128) == 0

def test_power_converter():
    from hp_ctl.protocol import power_converter
    assert power_converter(1) == 0.0
    assert power_converter(10) == 1.8
