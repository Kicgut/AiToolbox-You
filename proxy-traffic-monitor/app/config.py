from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import logging
import yaml


@dataclass
class ClashApiConfig:
    base_url: str = "127.0.0.1:9090"
    secret: str = ""


@dataclass
class ServerConfig:
    listen_port: int = 8899


@dataclass
class StorageConfig:
    db_path: str = "./data/traffic.db"
    retention_days: int = 30


@dataclass
class CollectorConfig:
    minute_flush_interval_sec: int = 60
    connlog_flush_interval_sec: int = 10
    cleanup_interval_hours: int = 24
    ws_reconnect_backoff_sec: List[int] = field(default_factory=lambda: [1, 2, 5, 10, 30])


@dataclass
class Config:
    clash_api: ClashApiConfig = field(default_factory=ClashApiConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)


logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> Config:
    data: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Config file %s not found, using defaults", path)

    clash_api = ClashApiConfig(**data.get("clash_api", {}))
    server = ServerConfig(**data.get("server", {}))
    storage = StorageConfig(**data.get("storage", {}))

    collector_raw = data.get("collector", {})
    collector = CollectorConfig(**collector_raw) if collector_raw else CollectorConfig()

    return Config(clash_api=clash_api, server=server, storage=storage, collector=collector)
