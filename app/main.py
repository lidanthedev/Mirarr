
from contextlib import asynccontextmanager
from pathlib import Path

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes_api import router as api_router
from app.api.routes_ui import router as ui_router
from app.api.routes_plugins import router as plugins_router
from app.core.auth import BasicAuthMiddleware
from app.plugins.loader import load_plugins
from app.providers import ProviderRegistry
from app.services.download_manager import download_manager_lifespan

logger = logging.getLogger(__name__)

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Application lifespan context manager."""
    try:
        load_plugins()
        async with download_manager_lifespan(app):
            yield
    finally:
        for provider in ProviderRegistry.all():
            if hasattr(provider, "aclose"):
                try:
                    await provider.aclose()
                except Exception:
                    logger.exception("Error closing provider %s", provider.name)
        ProviderRegistry.clear()


# Initialize FastAPI with overarching lifespan
app = FastAPI(
    title="Mirrarr",
    description="A Sonarr-like PVR for Direct Download content",
    version="0.1.0",
    lifespan=app_lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Add authentication middleware (only active when AUTH_USERNAME + AUTH_PASSWORD are set)
app.add_middleware(BasicAuthMiddleware)

# Initialize Jinja2 templates (shared across routers)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Include routers
app.include_router(ui_router)
app.include_router(plugins_router)
app.include_router(api_router, prefix="/api")
