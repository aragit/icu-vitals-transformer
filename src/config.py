"""Application configuration via Pydantic Settings."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_app_version() -> str:
    """Application version sourced from installed package metadata.

    Single source of truth = ``pyproject.toml`` ``version`` (read via
    ``importlib.metadata``). When the package is not installed (e.g. running
    directly from a source checkout on the test path), fall back to the
    canonical release version so ``GET /discover`` and ``GET /health`` always
    report a concrete string instead of failing at import time.
    """
    try:
        return _pkg_version("icu-vitals-transformer")
    except PackageNotFoundError:
        return "0.9.1"


class Settings(BaseSettings):
    """ICU Vitals Transformer configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "icu-vitals-transformer"
    app_version: str = _default_app_version()
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Forecasting
    forecast_horizons: list[int] = [60, 240, 720]  # minutes: 1h, 4h, 12h

    # MCP
    mcp_server_name: str = "icu-vitals-transformer"
    mcp_transport: str = "stdio"  # stdio (dev) or http (streamable-http, prod)
    mcp_transport_env: str = "MCP_TRANSPORT"  # env var override name


settings = Settings()
