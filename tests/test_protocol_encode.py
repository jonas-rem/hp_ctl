# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import pytest

from hp_ctl.protocol import STANDARD_CODEC, Message


class TestEncode:
    """Test encoding of writable fields"""

    def test_encode_creates_valid_buffer(self):
        """Encode creates a 110-byte buffer with correct header"""
        msg = Message(packet_type=0x10, fields={"dhw_target_temp": 50.0})
        encoded = STANDARD_CODEC.encode(msg)

        assert len(encoded) == 110
        assert encoded[0:4] == bytes([0xF1, 0x6C, 0x01, 0x10])
        # All other bytes should be 0x00 except byte 42
        assert encoded[42] == 178  # 50 + 128
        assert sum(encoded[4:42]) == 0
        assert sum(encoded[43:110]) == 0

    def test_roundtrip_dhw_temp(self):
        """DHW temperature survives encode->decode round-trip"""
        original_value = 55.0
        msg = Message(packet_type=0x10, fields={"dhw_target_temp": original_value})

        encoded = STANDARD_CODEC.encode(msg)
        decoded = STANDARD_CODEC.decode(encoded, 0x10)

        assert decoded.fields["dhw_target_temp"] == original_value

    def test_roundtrip_zone1_temp(self):
        """Zone 1 heat target temperature survives round-trip"""
        original_value = 45.0
        msg = Message(packet_type=0x10, fields={"zone1_heat_target_temp": original_value})

        encoded = STANDARD_CODEC.encode(msg)
        # Check it was written to byte 38
        assert encoded[38] == 173  # 45 + 128

        decoded = STANDARD_CODEC.decode(encoded, 0x10)
        assert decoded.fields["zone1_heat_target_temp"] == original_value

    def test_encode_quiet_mode(self):
        """Quiet mode is correctly encoded to bit field positions"""
        # Level 2 -> inverse returns 11 (0b01011)
        # Shifting by 3 bits -> 11 << 3 = 88
        msg = Message(packet_type=0x10, fields={"quiet_mode": "Level 2"})

        encoded = STANDARD_CODEC.encode(msg)
        assert encoded[7] == 88

    def test_hp_status_encode(self):
        """HP status (On/Off) is correctly encoded"""
        msg_on = Message(packet_type=0x10, fields={"hp_status": "On"})
        encoded_on = STANDARD_CODEC.encode(msg_on)
        assert encoded_on[4] == 2

        msg_off = Message(packet_type=0x10, fields={"hp_status": "Off"})
        encoded_off = STANDARD_CODEC.encode(msg_off)
        assert encoded_off[4] == 1

    def test_operating_mode_encode(self):
        """Operating mode is correctly encoded"""
        msg = Message(packet_type=0x10, fields={"operating_mode": "Heat"})
        encoded = STANDARD_CODEC.encode(msg)
        assert encoded[6] == 0x22  # 34

    def test_validation_ranges(self):
        """Values outside valid range raise ValueError"""
        with pytest.raises(ValueError, match="below minimum"):
            STANDARD_CODEC.encode(Message(packet_type=0x10, fields={"dhw_target_temp": 39.0}))

        with pytest.raises(ValueError, match="exceeds maximum"):
            STANDARD_CODEC.encode(Message(packet_type=0x10, fields={"dhw_target_temp": 76.0}))

    def test_non_writable_field(self):
        """Attempting to write non-writable field raises ValueError"""
        with pytest.raises(ValueError, match="not writable"):
            STANDARD_CODEC.encode(Message(packet_type=0x10, fields={"outdoor_temp": 20.0}))
