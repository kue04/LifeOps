from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("LIFEOPS_DB_PATH", "lifeops.sqlite3")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    llm_mode: str = os.getenv("LIFEOPS_LLM_MODE", "mock")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    weather_provider: str = os.getenv("WEATHER_PROVIDER", "mock")
    openweather_api_key: str = os.getenv("OPENWEATHER_API_KEY", "")
    place_provider: str = os.getenv("PLACE_PROVIDER", "mock")
    amap_api_key: str = os.getenv("AMAP_API_KEY", "")
    search_provider: str = os.getenv("SEARCH_PROVIDER", "mock")
    bocha_api_key: str = os.getenv("BOCHA_API_KEY", "")
    search_freshness: str = os.getenv("SEARCH_FRESHNESS", "noLimit")
    search_summary: bool = os.getenv("SEARCH_SUMMARY", "true").lower() == "true"
    search_count: int = int(os.getenv("SEARCH_COUNT", "8"))
    search_include: str = os.getenv("SEARCH_INCLUDE", "")
    search_exclude: str = os.getenv("SEARCH_EXCLUDE", "")


settings = Settings()
