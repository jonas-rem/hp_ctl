# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from hp_ctl.protocol import PROTOCOL, Message


@dataclass
class MessageTestCase:
    """Test case combining raw message, expected decoded result, and description"""
    name: str
    raw_hex: str
    expected: Message
    # Track which fields were explicitly specified
    expected_fields: set[str]


def _load_test_cases() -> dict:
    """Load test cases from YAML fixture file.

    Only loads valid message test cases. Invalid message tests (len, checksum)
    are handled by the UART layer and tested in test_uart.py.
    """
    fixture_path = (
        Path(__file__).parent / "fixtures" / "decoder_test_cases.yaml"
    )

    with open(fixture_path, "r") as f:
        data = yaml.safe_load(f)

    test_cases = {}
    for case_id, case_data in data["test_cases"].items():
        # Skip invalid message test cases - those are validated by UART layer
        if "should_raise" in case_data:
            continue

        # Clean up raw_hex by removing whitespace and newlines
        raw_hex = case_data["raw_hex"].replace(" ", "").replace("\n", "")

        # Build expected Message with only specified fields
        expected_dict = case_data.get("expected", {})

        # Extract packet_type if specified, default to 0x10 for backward
        # compatibility
        packet_type = expected_dict.get("packet_type", 0x10)

        message_kwargs = {"packet_type": packet_type, "fields": {}}

        for field_name, value in expected_dict.items():
            if field_name not in ("len", "checksum", "packet_type"):
                # Only decoded fields go in fields dict
                # (len and checksum are validated by UART layer, not protocol layer)
                message_kwargs["fields"][field_name] = value

        expected = Message(**message_kwargs)

        test_cases[case_id] = MessageTestCase(
            name=case_id,
            raw_hex=raw_hex,
            expected=expected,
            expected_fields=set(expected_dict.keys()),
        )

    return test_cases


TEST_CASES = _load_test_cases()


@pytest.fixture
def protocol():
    return PROTOCOL


def _validate_message(decoded: Message, expected: Message, expected_fields: set[str]) -> None:
    """Validate decoded message against expected values.

    Only checks fields that were explicitly specified in the test case.
    Note: len and checksum are validated by the UART layer, not the protocol layer.
    """
    # Check packet_type if specified
    if 'packet_type' in expected_fields:
        assert decoded.packet_type == expected.packet_type, (
            f"packet_type mismatch: 0x{decoded.packet_type:02x} != 0x{expected.packet_type:02x}"
        )

    # Check decoded fields dict
    for field_name in expected_fields:
        if field_name not in ('len', 'checksum', 'packet_type'):
            expected_value = expected.fields.get(field_name)
            decoded_value = decoded.fields.get(field_name)
            assert decoded_value == expected_value, (
                f"{field_name} mismatch: {decoded_value} != {expected_value}"
            )


@pytest.mark.parametrize("test_case", TEST_CASES.values(), ids=lambda tc: tc.name)
def test_decoder_parses_valid_message(protocol, test_case):
    """Test that decoder can parse a valid UART message."""
    raw_bytes = bytes.fromhex(test_case.raw_hex)
    message = protocol.decode(raw_bytes)
    assert isinstance(message, Message)
    _validate_message(message, test_case.expected, test_case.expected_fields)


def test_temp_converter():
    from hp_ctl.protocol import temp_converter
    assert temp_converter(176) == 48
    assert temp_converter(128) == 0
