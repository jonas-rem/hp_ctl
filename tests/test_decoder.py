import pytest
from dataclasses import dataclass
from pathlib import Path
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
    fixture_path = Path(__file__).parent / "fixtures" / "decoder_test_cases.yaml"

    with open(fixture_path, "r") as f:
        data = yaml.safe_load(f)

    test_cases = {}
    for case_id, case_data in data["test_cases"].items():
        # Clean up raw_hex by removing whitespace and newlines
        raw_hex = case_data["raw_hex"].replace(" ", "").replace("\n", "")

        # Build expected Message with only specified fields
        expected_dict = case_data.get("expected", {})
        expected = Message(
            len=expected_dict.get("len", 0),
            checksum=bytes.fromhex(expected_dict.get("checksum", "")),
            quiet_mode=expected_dict.get("quiet_mode", 0),
        )

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
    if expected.len != 0:
        assert decoded.len == expected.len, f"len mismatch: {decoded.len} != {expected.len}"
    if expected.checksum != b"":
        assert decoded.checksum == expected.checksum, f"checksum mismatch: {decoded.checksum.hex()} != {expected.checksum.hex()}"
    if expected.quiet_mode != 0:
        assert decoded.quiet_mode == expected.quiet_mode, f"quiet_mode mismatch: {decoded.quiet_mode} != {expected.quiet_mode}"


@pytest.mark.parametrize("test_case", TEST_CASES.values(), ids=lambda tc: tc.name)
def test_decoder_parses_valid_message(decoder, test_case):
    """Test that decoder can parse a valid UART message and validate against expected values"""
    raw_bytes = bytes.fromhex(test_case.raw_hex)
    message = decoder.decode(raw_bytes)

    assert isinstance(message, Message)
    _validate_message(message, test_case.expected)
