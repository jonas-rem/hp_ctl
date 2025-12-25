# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 Jonas Remmert <j.remmert@mailbox.org>

import logging
from pathlib import Path
from typing import Any

import yaml

from hp_ctl.protocol import EXTRA_FIELDS, STANDARD_FIELDS

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config.yaml file.

    Returns:
        Configuration dictionary with uart, mqtt and optional limits.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If required fields are missing or limits are invalid.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.debug("Loading config from %s", config_path)
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    # Validate required sections
    required_sections = {
        "uart": ["port", "baudrate"],
        "mqtt": ["broker", "port"],
    }

    for section, fields in required_sections.items():
        if section not in config:
            raise ValueError(f"Missing required section: {section}")
        for field in fields:
            if field not in config[section]:
                raise ValueError(f"Missing required field: {section}.{field}")

    # Validate optional limits
    if "limits" in config and config["limits"]:
        _validate_limits(config["limits"])

    logger.info("Config loaded successfully")
    return config


def _validate_limits(limits: dict[str, Any]) -> None:
    """Validate user-defined limits against protocol constraints."""
    # Combine all known fields
    all_fields = {f.name: f for f in STANDARD_FIELDS + EXTRA_FIELDS}

    for field_name, field_limits in limits.items():
        if field_name not in all_fields:
            raise ValueError(f"Invalid field in limits: '{field_name}'")

        field = all_fields[field_name]
        if not field.writable:
            raise ValueError(f"Field '{field_name}' in limits is not writable")

        if not isinstance(field_limits, dict) or "max" not in field_limits:
            continue

        user_max = field_limits["max"]
        if field.max_value is not None and user_max > field.max_value:
            raise ValueError(
                f"User-defined max {user_max} for '{field_name}' "
                f"exceeds protocol maximum {field.max_value}"
            )
        if field.min_value is not None and user_max < field.min_value:
            raise ValueError(
                f"User-defined max {user_max} for '{field_name}' "
                f"is below protocol minimum {field.min_value}"
            )
