from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_API_CONFIG_PATH = Path("config/api_config.json")


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    api_key: str
    multimodal_model: str


def load_api_config(path: str | Path = DEFAULT_API_CONFIG_PATH) -> ApiConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"API config file not found: {config_path}. Copy config/api_config.example.json to config/api_config.json and fill it in."
        )
    with config_path.open("r", encoding="utf-8") as config_file:
        payload = json.load(config_file)

    base_url = str(payload.get("base_url", "")).strip()
    api_key = str(payload.get("api_key", "")).strip()
    if not base_url:
        raise ValueError(f"base_url is empty in API config: {config_path}")
    if not api_key:
        raise ValueError(f"api_key is empty in API config: {config_path}")
    multimodal_model = str(payload.get("multimodal_model", "")).strip()
    if not multimodal_model:
        raise ValueError(f"multimodal_model is empty in API config: {config_path}")
    return ApiConfig(
        base_url=base_url,
        api_key=api_key,
        multimodal_model=multimodal_model,
    )
