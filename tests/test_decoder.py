import pytest
from hp_ctl.decoder import Decoder
from hp_ctl.message import Message


@pytest.fixture
def decoder():
    return Decoder()


@pytest.fixture
def sample_message():
    """Sample UART message from Panasonic Aquarea Heatpump"""
    # Format: [Header(2)] [Data(32)] [Checksum(2)]
    return bytes.fromhex("71110A00000000000000000000000000000000000000000000000000000000000000000000B8")


def test_decoder_parses_valid_message(decoder, sample_message):
    """Test that decoder can parse a valid UART message"""
    message = decoder.decode(sample_message)
    
    assert isinstance(message, Message)
    assert message.header == bytes.fromhex("7111")
    assert len(message.data) == 32
    assert message.checksum == bytes.fromhex("B8")


def test_decoder_validates_checksum(decoder, sample_message):
    """Test that decoder validates message checksum"""
    # Corrupt the checksum
    corrupted = sample_message[:-1] + bytes([0xFF])
    
    with pytest.raises(ValueError, match="Invalid checksum"):
        decoder.decode(corrupted)
