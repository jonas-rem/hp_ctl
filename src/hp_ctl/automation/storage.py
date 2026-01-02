# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

"""SQLite storage for automation data."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Current schema version
SCHEMA_VERSION = 1

# Database schema - applied directly without migrations
SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS snapshots (
        timestamp TEXT PRIMARY KEY,
        outdoor_temp REAL,
        heat_power_generation REAL,
        heat_power_consumption REAL,
        inlet_water_temp REAL,
        outlet_water_temp REAL,
        hp_status TEXT,
        operating_mode TEXT,
        zone1_actual_temp REAL
    );

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );

    INSERT OR REPLACE INTO schema_version (version) VALUES (1);
"""


@dataclass
class HeatPumpSnapshot:
    """Represents a single heat pump data snapshot."""

    timestamp: datetime
    outdoor_temp: Optional[float] = None
    heat_power_generation: Optional[float] = None  # Watts
    heat_power_consumption: Optional[float] = None  # Watts
    inlet_water_temp: Optional[float] = None
    outlet_water_temp: Optional[float] = None
    zone1_actual_temp: Optional[float] = None
    hp_status: Optional[str] = None
    operating_mode: Optional[str] = None
    # Runtime-only field (not persisted to DB)
    three_way_valve: Optional[str] = None


@dataclass
class DailySummary:
    """Daily aggregated statistics."""

    date: str  # YYYY-MM-DD
    total_heat_kwh: float  # Integrated heat energy generated
    total_consumption_kwh: float  # Integrated electrical energy consumed
    avg_cop: float  # Average coefficient of performance
    avg_outdoor_temp: float
    runtime_hours: float


class AutomationStorage:
    """SQLite storage manager for automation data."""

    def __init__(self, db_path: str) -> None:
        """Initialize storage with database path.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = Path(db_path)
        self._ensure_db_directory()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def _ensure_db_directory(self) -> None:
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Database directory: %s", self.db_path.parent)

    def _initialize_schema(self) -> None:
        """Initialize database schema."""
        cursor = self.conn.cursor()

        # Check if schema is already initialized
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone() is None:
            # Create schema from scratch
            logger.info("Creating database schema (version %d)", SCHEMA_VERSION)
            cursor.executescript(SCHEMA_SQL)
            self.conn.commit()
        else:
            # Schema already exists
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            current_version = row[0] if row else 0
            logger.info("Database schema already initialized (version %d)", current_version)

        logger.info("Database ready (version %d)", SCHEMA_VERSION)

    def insert_snapshot(self, snapshot: HeatPumpSnapshot) -> None:
        """Insert a heat pump snapshot into the database.

        Args:
            snapshot: HeatPumpSnapshot instance to store.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO snapshots (
                timestamp, outdoor_temp, heat_power_generation, heat_power_consumption,
                inlet_water_temp, outlet_water_temp,
                zone1_actual_temp, hp_status, operating_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.timestamp.isoformat(),
                snapshot.outdoor_temp,
                snapshot.heat_power_generation,
                snapshot.heat_power_consumption,
                snapshot.inlet_water_temp,
                snapshot.outlet_water_temp,
                snapshot.zone1_actual_temp,
                snapshot.hp_status,
                snapshot.operating_mode,
            ),
        )
        self.conn.commit()
        logger.debug("Inserted snapshot at %s", snapshot.timestamp)

    def get_snapshots(self, start_date: datetime, end_date: datetime) -> list[HeatPumpSnapshot]:
        """Retrieve snapshots within a date range.

        Args:
            start_date: Start of date range (inclusive).
            end_date: End of date range (exclusive).

        Returns:
            List of HeatPumpSnapshot instances.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM snapshots
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )

        snapshots = []
        for row in cursor.fetchall():
            snapshots.append(
                HeatPumpSnapshot(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    outdoor_temp=row["outdoor_temp"],
                    heat_power_generation=row["heat_power_generation"],
                    heat_power_consumption=row["heat_power_consumption"],
                    inlet_water_temp=row["inlet_water_temp"],
                    outlet_water_temp=row["outlet_water_temp"],
                    zone1_actual_temp=row["zone1_actual_temp"],
                    hp_status=row["hp_status"],
                    operating_mode=row["operating_mode"],
                )
            )

        return snapshots

    def get_daily_summary(self, date: datetime) -> Optional[DailySummary]:
        """Calculate daily summary statistics for a given date.

        Uses trapezoidal rule to integrate power over time:
        Energy (kWh) = Σ [(P₁ + P₂) / 2 × Δt] / 3600 / 1000

        Args:
            date: Date to calculate summary for.

        Returns:
            DailySummary instance or None if no data available.
        """
        # Get all snapshots for the day
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        snapshots = self.get_snapshots(start, end)

        if not snapshots:
            logger.debug("No snapshots found for %s", date.date())
            return None

        # Calculate integrated energy using trapezoidal rule
        total_heat_kwh = 0.0
        total_consumption_kwh = 0.0
        runtime_seconds = 0.0

        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]
            curr = snapshots[i]

            # Calculate time delta in seconds
            delta_t = (curr.timestamp - prev.timestamp).total_seconds()

            # Trapezoidal integration for heat generation
            if prev.heat_power_generation is not None and curr.heat_power_generation is not None:
                avg_power = (prev.heat_power_generation + curr.heat_power_generation) / 2
                total_heat_kwh += (avg_power * delta_t) / 3600 / 1000

            # Trapezoidal integration for consumption
            if prev.heat_power_consumption is not None and curr.heat_power_consumption is not None:
                avg_power = (prev.heat_power_consumption + curr.heat_power_consumption) / 2
                total_consumption_kwh += (avg_power * delta_t) / 3600 / 1000

            # Track runtime when hp_status is "On"
            if curr.hp_status == "On":
                runtime_seconds += delta_t

        # Calculate average COP
        avg_cop = total_heat_kwh / total_consumption_kwh if total_consumption_kwh > 0 else 0.0

        # Calculate average outdoor temperature
        outdoor_temps = [s.outdoor_temp for s in snapshots if s.outdoor_temp is not None]
        avg_outdoor_temp = sum(outdoor_temps) / len(outdoor_temps) if outdoor_temps else 0.0

        return DailySummary(
            date=date.date().isoformat(),
            total_heat_kwh=total_heat_kwh,
            total_consumption_kwh=total_consumption_kwh,
            avg_cop=avg_cop,
            avg_outdoor_temp=avg_outdoor_temp,
            runtime_hours=runtime_seconds / 3600,
        )

    def cleanup_old_data(self, retention_days: int) -> int:
        """Delete snapshots older than retention period.

        Args:
            retention_days: Number of days to keep.

        Returns:
            Number of rows deleted.
        """
        cutoff = datetime.now() - timedelta(days=retention_days)
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM snapshots WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )
        deleted = cursor.rowcount
        self.conn.commit()
        logger.info("Deleted %d snapshots older than %d days", deleted, retention_days)
        return deleted

    def get_snapshot_count(self) -> int:
        """Get total number of snapshots in database.

        Returns:
            Total snapshot count.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM snapshots")
        return cursor.fetchone()[0]

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
        logger.debug("Database connection closed")
