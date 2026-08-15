"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.config import settings
from src.adapters.rest.middleware import CorrelationIdMiddleware
from src.adapters.rest.routes import (
    discovery,
    health as health_v2,
    metrics as metrics_v2,
    vitals_v2,
)


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

app.add_middleware(CorrelationIdMiddleware)

app.include_router(vitals_v2.router)
app.include_router(health_v2.router)
app.include_router(metrics_v2.router)
app.include_router(discovery.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
    }
