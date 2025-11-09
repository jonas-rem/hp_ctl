import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config.yaml file.

    Returns:
        Configuration dictionary with uart and mqtt settings.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If required fields are missing.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.debug("Loading config from %s", config_path)
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    # Validate required fields
    required_fields = {
        "uart": ["port", "baudrate"],
        "mqtt": ["broker", "port"],
    }

    for section, fields in required_fields.items():
        if section not in config:
            raise ValueError(f"Missing required section: {section}")
        for field in fields:
            if field not in config[section]:
                raise ValueError(f"Missing required field: {section}.{field}")

    logger.info("Config loaded successfully")
    return config
