"""Example test module to demonstrate TDD structure."""

import pytest


class TestExample:
    """Example test class."""

    @pytest.mark.unit
    def test_sample_fixture(self, sample_fixture):
        """Test that demonstrates fixture usage."""
        assert sample_fixture["key"] == "value"

    @pytest.mark.unit
    def test_simple_assertion(self):
        """Simple test example."""
        assert 1 + 1 == 2
