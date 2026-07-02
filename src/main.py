"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.config import settings
from src.api.routes import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    yield
    logger.info(f"Shutting down {settings.app_name}")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="MCP clinical forecasting skill for ICU vital signs",
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/health", tags=["health"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
    }
