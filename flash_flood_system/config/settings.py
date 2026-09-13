"""Central configuration loader: merges config.yaml (non-secret) with .env (secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


def _load_yaml() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_config() -> dict:
    """Returns the parsed config.yaml as a dict."""
    return _load_yaml()


def get_db_config() -> DBConfig:
    return DBConfig(
        host=os.environ.get("FFS_DB_HOST", "localhost"),
        port=int(os.environ.get("FFS_DB_PORT", 5432)),
        name=os.environ.get("FFS_DB_NAME", "flash_flood_db"),
        user=os.environ.get("FFS_DB_USER", "postgres"),
        password=os.environ.get("FFS_DB_PASSWORD", ""),
    )


def get_mqtt_config() -> dict:
    return {
        "host": os.environ.get("FFS_MQTT_HOST", "localhost"),
        "port": int(os.environ.get("FFS_MQTT_PORT", 1883)),
    }


def get_redis_url() -> str:
    return os.environ.get("FFS_REDIS_URL", "redis://localhost:6379/0")


CONFIG = get_config()
GEOGRAPHIC_CRS = CONFIG["crs"]["geographic"]
PROJECTED_CRS = CONFIG["crs"]["projected"]
BASE_GRID_RESOLUTION_M = CONFIG["grid"]["base_resolution_m"]
HIGH_RISK_GRID_RESOLUTION_M = CONFIG["grid"]["high_risk_resolution_m"]
MODEL_VERSION = CONFIG["project"]["model_version"]
