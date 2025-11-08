from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from hp_ctl.decoder import Decoder
from hp_ctl.message import Message


@dataclass
class MessageTestCase:
    """Test case combining raw message, expected decoded result, and description"""
    name: str
    raw_hex: str
    expected: Message


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
        message_kwargs = {}
        for field_name in Message.__dataclass_fields__:
            if field_name in expected_dict:
                value = expected_dict[field_name]
                # Convert hex strings to bytes for bytes fields
                if field_name == "checksum" and isinstance(value, str):
                    message_kwargs[field_name] = bytes.fromhex(value)
                else:
                    message_kwargs[field_name] = value

        expected = Message(**message_kwargs)

        test_cases[case_id] = MessageTestCase(
            name=case_id,
            raw_hex=raw_hex,
            expected=expected,
        )

    return test_cases


TEST_CASES = _load_test_cases()


@pytest.fixture
def decoder():
    return Decoder()


def _validate_message(decoded: Message, expected: Message) -> None:
    """Validate decoded message against expected values.

    Only checks fields that are specified (non-zero/non-empty).
    """
    for field_name in expected.__dataclass_fields__:
        expected_value = getattr(expected, field_name)

        # Skip unspecified fields (0 for int, b"" for bytes)
        if expected_value == 0 or expected_value == b"":
            continue

        decoded_value = getattr(decoded, field_name)
        assert decoded_value == expected_value, (
            f"{field_name} mismatch: {decoded_value} != {expected_value}"
        )


@pytest.mark.parametrize("test_case", TEST_CASES.values(), ids=lambda tc: tc.name)
def test_decoder_parses_valid_message(decoder, test_case):
    """Test that decoder can parse a valid UART message.

    Validates decoded message against expected values from test case.
    """
    raw_bytes = bytes.fromhex(test_case.raw_hex)
    message = decoder.decode(raw_bytes)

    assert isinstance(message, Message)
    _validate_message(message, test_case.expected)
