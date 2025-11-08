"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_fixture():
    """Example fixture for tests."""
    return {"key": "value"}
