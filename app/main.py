from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes_api import router as api_router
from app.core.auth import BasicAuthMiddleware
from app.api.routes_ui import router as ui_router
from app.providers import ProviderRegistry, register_provider
from app.providers.a111477_provider import A111477Provider
from app.providers.acermovies_provider import AcerMoviesProvider
from app.providers.rivestream_provider import RiveStreamProvider
from app.providers.vadapav_provider import VadapavProvider
from app.services.download_manager import download_manager_lifespan

import logging

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
        # Setup download manager
        async with download_manager_lifespan(app):
            yield
    finally:
        # Teardown providers
        for provider in ProviderRegistry.all():
            if hasattr(provider, "aclose"):
                try:
                    await provider.aclose()
                except Exception:
                    logger.exception("Error closing provider %s", provider.name)


# Initialize FastAPI with overarching lifespan
app = FastAPI(
    title="Mirrarr",
    description="A Sonarr-like PVR for Direct Download content",
    version="0.1.0",
    lifespan=app_lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Add authentication middleware for all routes
app.add_middleware(BasicAuthMiddleware)

# Initialize Jinja2 templates (shared across routers)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Register providers
register_provider(VadapavProvider())
register_provider(A111477Provider())
register_provider(RiveStreamProvider())
register_provider(AcerMoviesProvider())

# Include routers
app.include_router(ui_router)
app.include_router(api_router, prefix="/api")
