# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import pytest

from hp_ctl.protocol import STANDARD_FIELDS, Message, MessageCodec


def test_user_max_limit_enforced():
    """User-defined max limit is enforced during encoding"""
    user_limits = {"dhw_target_temp": {"max": 55.0}}
    codec = MessageCodec(STANDARD_FIELDS, user_limits=user_limits)

    # Should succeed (within limit)
    msg = Message(packet_type=0x10, fields={"dhw_target_temp": 55.0})
    encoded = codec.encode(msg)
    assert encoded is not None

    # Should fail (exceeds user limit)
    msg = Message(packet_type=0x10, fields={"dhw_target_temp": 56.0})
    with pytest.raises(ValueError, match="exceeds user-defined maximum 55.0"):
        codec.encode(msg)


def test_user_limit_below_protocol_max():
    """User limit is more restrictive than protocol limit"""
    # Protocol max for dhw_target_temp is 75.0
    user_limits = {"dhw_target_temp": {"max": 60.0}}
    codec = MessageCodec(STANDARD_FIELDS, user_limits=user_limits)

    # 60.0 should work (user max)
    msg = Message(packet_type=0x10, fields={"dhw_target_temp": 60.0})
    assert codec.encode(msg) is not None

    # 61.0 should fail (protocol allows, but user restricts)
    msg = Message(packet_type=0x10, fields={"dhw_target_temp": 61.0})
    with pytest.raises(ValueError, match="exceeds user-defined maximum 60.0"):
        codec.encode(msg)


def test_non_writable_field_in_limits_validation():
    """Validation in config.py prevents setting limits on non-writable fields"""
    from hp_ctl.config import _validate_limits

    # outdoor_temp is not writable
    invalid_limits = {"outdoor_temp": {"max": 30.0}}
    with pytest.raises(ValueError, match="not writable"):
        _validate_limits(invalid_limits)


def test_exceeding_protocol_max_in_limits_validation():
    """Validation in config.py prevents setting user max above protocol max"""
    from hp_ctl.config import _validate_limits

    # dhw_target_temp protocol max is 75.0
    invalid_limits = {"dhw_target_temp": {"max": 80.0}}
    with pytest.raises(ValueError, match="exceeds protocol maximum 75.0"):
        _validate_limits(invalid_limits)
