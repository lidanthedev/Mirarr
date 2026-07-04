"""UI routes for managing filesystem plugins."""

import logging
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.plugins.loader import get_plugin_overview, reload_plugins, set_plugin_enabled, set_plugin_order

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@router.get("/plugins")
async def plugins_page(request: Request):
    """Render the plugin management page."""
    return templates.TemplateResponse(
        request=request,
        name="plugins.html",
        context={
            "page_title": "Plugins",
            "plugins": get_plugin_overview(),
        },
    )


@router.get("/plugins/list")
async def plugins_list(request: Request):
    """Return the plugin list partial."""
    return templates.TemplateResponse(
        request=request,
        name="partials/plugin_list.html",
        context={"plugins": get_plugin_overview()},
    )


@router.post("/plugins/reload")
async def reload_plugins_view(request: Request):
    """Reload plugins and refresh the page state."""
    reload_plugins(Path(get_settings().data_dir))
    return templates.TemplateResponse(
        request=request,
        name="partials/plugin_list.html",
        context={"plugins": get_plugin_overview()},
    )


@router.post("/plugins/{plugin_id}/toggle")
async def toggle_plugin(request: Request, plugin_id: str):
    """Toggle a plugin and reload the runtime."""
    overview = get_plugin_overview()
    current = next((item for item in overview if item["plugin_id"] == plugin_id), None)
    if current is None:
        return JSONResponse({"message": f"Plugin '{plugin_id}' not found"}, status_code=404)

    set_plugin_enabled(Path(get_settings().data_dir), plugin_id, not bool(current["enabled"]))
    return templates.TemplateResponse(
        request=request,
        name="partials/plugin_list.html",
        context={"plugins": get_plugin_overview()},
    )


@router.post("/plugins/reorder")
async def reorder_plugins(request: Request, payload: dict[str, object] = Body(...)):
    """Persist plugin order and reload the runtime."""
    ordered_ids = payload.get("order", [])
    if not isinstance(ordered_ids, list):
        return JSONResponse({"message": "order must be a list"}, status_code=422)

    set_plugin_order(Path(get_settings().data_dir), [str(item) for item in ordered_ids])
    return templates.TemplateResponse(
        request=request,
        name="partials/plugin_list.html",
        context={"plugins": get_plugin_overview()},
    )
