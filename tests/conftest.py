# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_fixture():
    """Example fixture for tests."""
    return {"key": "value"}
