"""UI routes returning HTML via Jinja2 templates."""

from pydantic import AfterValidator
from typing import Annotated
import logging
from pathlib import Path

import asyncio
from fastapi import APIRouter, Request, Form
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from app.services.tmdb import (
    search_tmdb,
    MediaType,
    get_series_details,
)
from app.services.search import (
    get_provider_results_for_movie,
    get_provider_results_for_episode,
    get_single_provider_results_for_movie,
    get_single_provider_results_for_episode,
    select_best_result,
)
from app.core.config import get_settings
from app.providers import ProviderRegistry
from app.services.download_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)

# Templates directory
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@router.get("/")
async def dashboard(request: Request):
    """Render the main dashboard page (search all)."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"media_type": "all", "page_title": "Search for Content"},
    )


@router.get("/movies")
async def movies_page(request: Request):
    """Render the movies search page."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"media_type": "movie", "page_title": "Search Movies"},
    )


@router.get("/tv")
async def tv_page(request: Request):
    """Render the TV shows search page."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"media_type": "tv", "page_title": "Search TV Shows"},
    )


@router.post("/search")
async def search(
    request: Request,
    query: str = Form(...),
    media_type: str = Form("all"),
):
    """Handle search form submission and return HTML partial."""
    if media_type == "movie":
        mt = MediaType.MOVIE
    elif media_type in ("tv", "series"):
        mt = MediaType.SERIES
    else:
        mt = MediaType.ALL

    results = await search_tmdb(query, mt)

    return templates.TemplateResponse(
        request=request,
        name="partials/search_results.html",
        context={"results": results, "query": query},
    )


@router.get("/series/{tmdb_id}")
async def series_modal(
    request: Request,
    tmdb_id: int,
):
    """Return the TV series modal with all seasons and episodes."""
    series = await get_series_details(tmdb_id)

    return templates.TemplateResponse(
        request=request,
        name="partials/series_modal.html",
        context={
            "series": series,
            "seasons": series.seasons,
        },
    )


@router.get("/providers/{media_type}/{tmdb_id}")
async def provider_modal(
    request: Request,
    media_type: str,
    tmdb_id: int,
    title: str = "",
    poster_url: str = "",
    season: int = 1,
    episode: int = 1,
):
    """Return the provider selection modal with loading skeletons.

    Shows immediately with loading spinners for each provider,
    which then fetch their results independently via HTMX.
    """
    from app.services.tmdb import get_movie_details, get_series_details

    # Get media info for the header (fast TMDB lookup only)
    if media_type == "movie":
        media = await get_movie_details(tmdb_id)
        if not title:
            title = media.title
        if not poster_url and media.poster_url:
            poster_url = media.poster_url
    else:
        media = await get_series_details(tmdb_id)
        if not title:
            title = media.title
        if not poster_url and media.poster_url:
            poster_url = media.poster_url

    # Get list of all registered providers for loading skeletons
    provider_names = ProviderRegistry.names()
    settings = get_settings()

    return templates.TemplateResponse(
        request=request,
        name="partials/provider_modal.html",
        context={
            "provider_names": provider_names,
            "title": title,
            "poster_url": poster_url,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "season": season,
            "episode": episode,
            "media": media,
            "preferred_provider": settings.preferred_provider,
            "quality_limit": settings.quality_limit,
        },
    )


@router.get("/provider-results/{media_type}/{tmdb_id}/{provider_name}")
async def provider_result(
    request: Request,
    media_type: str,
    tmdb_id: int,
    provider_name: str,
    season: int = 1,
    episode: int = 1,
):
    """Fetch results from a single provider and return HTML partial.

    Called by HTMX on page load for each provider to enable incremental loading.
    """
    try:
        if media_type == "movie":
            _, results = await get_single_provider_results_for_movie(
                tmdb_id, provider_name
            )
        else:
            _, results = await get_single_provider_results_for_episode(
                tmdb_id, season, episode, provider_name
            )
    except asyncio.CancelledError:
        logger.warning(f"Request cancelled for provider {provider_name}")
        results = []
    except Exception as e:
        logger.error(f"Error fetching results for provider {provider_name}: {e}")
        results = []

    return templates.TemplateResponse(
        request=request,
        name="partials/provider_result.html",
        context={
            "provider_name": provider_name,
            "provider_results": results,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "season": season,
            "episode": episode,
        },
    )


@router.get("/auto-button/{media_type}/{tmdb_id}")
async def auto_button(
    request: Request,
    media_type: str,
    tmdb_id: int,
    season: int = 1,
    episode: int = 1,
):
    """Return the AUTO button after all providers have loaded.

    Waits for all providers to complete, then returns the best result button.
    """
    if media_type == "movie":
        _, results = await get_provider_results_for_movie(tmdb_id)
    else:
        _, results = await get_provider_results_for_episode(tmdb_id, season, episode)

    best_result = select_best_result(results)

    return templates.TemplateResponse(
        request=request,
        name="partials/auto_button.html",
        context={
            "best_result": best_result,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "season": season,
            "episode": episode,
        },
    )


@router.get("/episode/auto/{tmdb_id}/{season}/{episode}")
async def episode_auto(
    request: Request,
    tmdb_id: int,
    season: int,
    episode: int,
):
    """Auto-download best quality for an episode.

    Finds the best quality result and queues it for download.
    """
    _, results = await get_provider_results_for_episode(tmdb_id, season, episode)
    best = select_best_result(results)

    if best:
        # Actually queue the download with provider-specific yt_opts
        filename = best.filename
        provider_name = best.provider_name
        provider = ProviderRegistry.get(provider_name)
        if provider is None:
            logger.warning(f"Provider '{provider_name}' not found in registry")
            return templates.TemplateResponse(
                request=request,
                name="partials/toast.html",
                context={
                    "message": f"Provider '{provider_name}' not found",
                    "type": "error",
                },
            )
        yt_opts = provider.get_yt_opts()
        download_id = await manager.add_download(
            best.download_url, client_opts=yt_opts, custom_filename=filename or None
        )
        msg = (
            f"[DOWNLOAD QUEUED] ID={download_id} {best.quality} "
            f"from {best.source_site}: {best.download_url}"
        )
        logger.info(msg)

        display_name = filename if filename else best.quality

        return templates.TemplateResponse(
            request=request,
            name="partials/auto_download.html",
            context={
                "download_url": best.download_url,
                "quality": best.quality,
                "source": best.source_site,
                "download_id": download_id,
                "filename": filename,
                "display_name": display_name,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/toast.html",
        context={"message": "No downloads available", "type": "error"},
    )


@router.get("/movie/auto/{tmdb_id}")
async def movie_auto(
    request: Request,
    tmdb_id: int,
):
    """Auto-download best quality for a movie.

    Finds the best quality result and queues it for download.
    """
    _, results = await get_provider_results_for_movie(tmdb_id)
    best = select_best_result(results)

    if best:
        # Actually queue the download with provider-specific yt_opts
        filename = best.filename
        provider_name = best.provider_name
        provider = ProviderRegistry.get(provider_name)
        if provider is None:
            logger.warning(f"Provider '{provider_name}' not found in registry")
            return templates.TemplateResponse(
                request=request,
                name="partials/toast.html",
                context={
                    "message": f"Provider '{provider_name}' not found",
                    "type": "error",
                },
            )
        download_id = await manager.add_download(
            best.download_url,
            custom_filename=filename or None,
            client_opts=provider.get_yt_opts(),
        )
        msg = (
            f"[DOWNLOAD QUEUED] ID={download_id} {best.quality} "
            f"from {best.source_site}: {best.download_url}"
        )
        logger.info(msg)

        display_name = filename if filename else best.quality

        return templates.TemplateResponse(
            request=request,
            name="partials/auto_download.html",
            context={
                "download_url": best.download_url,
                "quality": best.quality,
                "source": best.source_site,
                "download_id": download_id,
                "filename": filename,
                "display_name": display_name,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/toast.html",
        context={"message": "No downloads available", "type": "error"},
    )


def _validate_url(v: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    return v


class DownloadQueueRequest(BaseModel):
    url: Annotated[str, AfterValidator(_validate_url)]
    quality: str = ""
    source: str = ""
    media_type: str = "movie"
    tmdb_id: int = 0
    season: int = 1
    episode: int = 1
    filename: str = ""


@router.post("/download/queue")
async def download_queue(
    request: Request,
    download_req: DownloadQueueRequest,
):
    """Queue a download via yt_dlp download manager.

    Shows toast notification and actually queues the download.
    """
    url = download_req.url
    quality = download_req.quality
    source = download_req.source
    media_type = download_req.media_type
    tmdb_id = download_req.tmdb_id
    season = download_req.season
    episode = download_req.episode
    filename = download_req.filename
    provider = ProviderRegistry.get(source)
    if provider is None:
        logging.warning(f"Provider '{source}' not found in registry")
        return templates.TemplateResponse(
            request=request,
            name="partials/toast.html",
            context={
                "message": f"Provider '{source}' not found",
                "type": "error",
            },
        )

    # Collect metadata from request parameters
    metadata = {
        "media_type": media_type,
        "tmdb_id": tmdb_id,
        "season": season,
        "episode": episode,
        "quality": quality,
        "source": source,
    }

    # Actually queue the download via the manager, with optional custom filename
    download_id = await manager.add_download(
        url,
        custom_filename=filename or None,
        client_opts=provider.get_yt_opts(),
        metadata=metadata,
    )
    msg = f"[DOWNLOAD QUEUED] ID={download_id} {quality} from {source}: {url}"
    logger.info(msg)

    display_name = filename if filename else quality

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Download queued: {display_name}",
            "download_id": download_id,
            "filename": filename,
            "display_name": display_name,
            "download_url": url,
            "quality": quality,
            "source": source,
        }
    )


@router.get("/downloads")
async def downloads_page(request: Request):
    """Render the downloads management page."""
    downloads = manager.get_all_downloads()
    return templates.TemplateResponse(
        request=request,
        name="downloads.html",
        context={
            "downloads": downloads,
            "page_title": "Downloads",
        },
    )


@router.get("/downloads/list")
async def downloads_list_partial(request: Request):
    """Return the downloads list partial (for HTMX polling)."""
    downloads = manager.get_all_downloads()
    return templates.TemplateResponse(
        request=request,
        name="partials/download_list.html",
        context={
            "downloads": downloads,
        },
    )
