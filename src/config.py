"""Application configuration via Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ICU Vitals Transformer configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "icu-vitals-transformer"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Forecasting
    forecast_horizons: list[int] = [60, 240, 720]  # minutes: 1h, 4h, 12h

    # MCP
    mcp_server_name: str = "icu-vitals-transformer"
    mcp_transport: str = "stdio"  # stdio or sse


settings = Settings()
