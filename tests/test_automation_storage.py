# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""Tests for automation storage module."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hp_ctl.automation.storage import AutomationStorage, HeatPumpSnapshot


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = AutomationStorage(str(db_path))
        yield storage
        storage.close()


def test_database_initialization(temp_db):
    """Test database is initialized with correct schema."""
    # Check tables exist
    cursor = temp_db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    assert "snapshots" in tables
    assert "schema_version" in tables

    # Check schema version
    cursor.execute("SELECT version FROM schema_version")
    version = cursor.fetchone()[0]
    assert version == 1


def test_insert_and_retrieve_snapshot(temp_db):
    """Test inserting and retrieving snapshots."""
    # Create snapshot
    timestamp = datetime(2025, 12, 26, 12, 0, 0)
    snapshot = HeatPumpSnapshot(
        timestamp=timestamp,
        outdoor_temp=5.5,
        heat_power_generation=3000.0,
        heat_power_consumption=1000.0,
        compressor_freq=45,
        inlet_water_temp=35.0,
        outlet_water_temp=40.0,
        hp_status="On",
        operating_mode="Heat",
    )

    # Insert
    temp_db.insert_snapshot(snapshot)

    # Retrieve
    start = timestamp.replace(hour=0, minute=0, second=0)
    end = start + timedelta(days=1)
    snapshots = temp_db.get_snapshots(start, end)

    assert len(snapshots) == 1
    retrieved = snapshots[0]
    assert retrieved.timestamp == timestamp
    assert retrieved.outdoor_temp == 5.5
    assert retrieved.heat_power_generation == 3000.0
    assert retrieved.compressor_freq == 45


def test_daily_summary_calculation(temp_db):
    """Test daily summary calculation with energy integration."""
    # Create snapshots over a day
    base_time = datetime(2025, 12, 26, 0, 0, 0)

    # Simulate heat pump running at constant power for 1 hour
    # Heat generation: 3000 W, Consumption: 1000 W
    # Expected: 3 kWh heat, 1 kWh consumption, COP = 3.0
    for i in range(13):  # 0-12 in 5-minute intervals = 1 hour
        timestamp = base_time + timedelta(minutes=i * 5)
        snapshot = HeatPumpSnapshot(
            timestamp=timestamp,
            outdoor_temp=5.0,
            heat_power_generation=3000.0,  # W
            heat_power_consumption=1000.0,  # W
            compressor_freq=45,
            hp_status="On",
        )
        temp_db.insert_snapshot(snapshot)

    # Calculate daily summary
    summary = temp_db.get_daily_summary(base_time)

    assert summary is not None
    assert summary.date == "2025-12-26"

    # Check energy integration (approximately 1 hour at 3000W = 3 kWh)
    # With 5-minute intervals: 12 intervals * 300s * 3000W / 3600 / 1000 = 3 kWh
    assert 2.9 < summary.total_heat_kwh < 3.1
    assert 0.9 < summary.total_consumption_kwh < 1.1

    # Check COP
    assert 2.8 < summary.avg_cop < 3.2

    # Check outdoor temp
    assert summary.avg_outdoor_temp == 5.0

    # Check runtime (approximately 1 hour)
    assert 0.9 < summary.runtime_hours < 1.1

    # Check max compressor freq
    assert summary.max_compressor_freq == 45


def test_cleanup_old_data(temp_db):
    """Test cleanup of old snapshots."""
    now = datetime.now()

    # Insert recent snapshot
    recent = HeatPumpSnapshot(timestamp=now, outdoor_temp=5.0)
    temp_db.insert_snapshot(recent)

    # Insert old snapshot (40 days ago)
    old_time = now - timedelta(days=40)
    old = HeatPumpSnapshot(timestamp=old_time, outdoor_temp=10.0)
    temp_db.insert_snapshot(old)

    # Verify both exist
    assert temp_db.get_snapshot_count() == 2

    # Cleanup with 30-day retention
    deleted = temp_db.cleanup_old_data(retention_days=30)

    # Verify old snapshot was deleted
    assert deleted == 1
    assert temp_db.get_snapshot_count() == 1

    # Verify remaining snapshot is the recent one
    start = now.replace(hour=0, minute=0, second=0)
    end = start + timedelta(days=1)
    snapshots = temp_db.get_snapshots(start, end)
    assert len(snapshots) == 1
    assert snapshots[0].outdoor_temp == 5.0


def test_no_summary_for_empty_day(temp_db):
    """Test daily summary returns None for days with no data."""
    date = datetime(2025, 12, 26)
    summary = temp_db.get_daily_summary(date)
    assert summary is None
