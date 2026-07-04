"""Search service for aggregating results from providers."""

import asyncio
import logging
from collections.abc import Sequence

from app.providers import ProviderRegistry
from app.providers.base import MovieResult, EpisodeResult
from app.models.media import Movie, TVSeries
from app.services.tmdb import get_movie_details, get_series_details
from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def get_provider_results_for_movie(
    tmdb_id: int,
) -> tuple[Movie, list[MovieResult]]:
    """Get download links from all providers for a movie.

    First fetches the Movie from TMDB, then queries all providers concurrently.

    Returns:
        Tuple of (Movie, list of MovieResult)
    """
    settings = get_settings()
    timeout = settings.provider_timeout
    movie = await get_movie_details(tmdb_id)
    providers = ProviderRegistry.all()

    async def fetch_from_provider(provider):
        try:
            return await asyncio.wait_for(provider.get_movie(movie), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout fetching movie from {provider.name} after {timeout}s"
            )
            return []
        except Exception as e:
            logger.error(f"Error fetching movie from {provider.name}: {e}", exc_info=e)
            return []

    provider_results = await asyncio.gather(
        *[fetch_from_provider(p) for p in providers]
    )

    results: list[MovieResult] = []
    for result_list in provider_results:
        results.extend(result_list)

    return movie, results


async def get_provider_results_for_episode(
    tmdb_id: int,
    season: int,
    episode: int,
) -> tuple[TVSeries, list[EpisodeResult]]:
    """Get download links from all providers for a TV episode.

    First fetches the TVSeries from TMDB, then queries all providers concurrently.

    Returns:
        Tuple of (TVSeries, list of EpisodeResult)
    """
    settings = get_settings()
    timeout = settings.provider_timeout
    series = await get_series_details(tmdb_id)
    providers = ProviderRegistry.all()

    async def fetch_from_provider(provider):
        try:
            return await asyncio.wait_for(
                provider.get_series_episode(series, season, episode), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout fetching episode from {provider.name} after {timeout}s"
            )
            return []
        except Exception as e:
            logger.error(
                f"Error fetching episode from {provider.name}: {e}", exc_info=e
            )
            return []

    provider_results = await asyncio.gather(
        *[fetch_from_provider(p) for p in providers]
    )

    results: list[EpisodeResult] = []
    for result_list in provider_results:
        results.extend(result_list)

    return series, results


async def get_single_provider_results_for_movie(
    tmdb_id: int,
    provider_name: str,
) -> tuple[Movie, list[MovieResult]]:
    """Get download links from a single provider for a movie.

    Returns:
        Tuple of (Movie, list of MovieResult)
    """
    settings = get_settings()
    timeout = settings.provider_timeout
    movie = await get_movie_details(tmdb_id)
    results: list[MovieResult] = []

    provider = ProviderRegistry.get(provider_name)
    if provider:
        try:
            provider_results = await asyncio.wait_for(
                provider.get_movie(movie), timeout=timeout
            )
            results.extend(provider_results)
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout fetching movie from {provider.name} after {timeout}s"
            )
        except Exception as e:
            logger.error(f"Error fetching movie from {provider.name}: {e}", exc_info=e)

    return movie, results


async def get_single_provider_results_for_episode(
    tmdb_id: int,
    season: int,
    episode: int,
    provider_name: str,
) -> tuple[TVSeries, list[EpisodeResult]]:
    """Get download links from a single provider for a TV episode.

    Returns:
        Tuple of (TVSeries, list of EpisodeResult)
    """
    settings = get_settings()
    timeout = settings.provider_timeout
    series = await get_series_details(tmdb_id)
    results: list[EpisodeResult] = []

    provider = ProviderRegistry.get(provider_name)
    if provider:
        try:
            provider_results = await asyncio.wait_for(
                provider.get_series_episode(series, season, episode), timeout=timeout
            )
            results.extend(provider_results)
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout fetching episode from {provider.name} after {timeout}s"
            )
        except Exception as e:
            logger.error(
                f"Error fetching episode from {provider.name}: {e}", exc_info=e
            )

    return series, results


def normalize_quality_score(quality_str: str | None) -> int:
    """Normalize quality string to an integer score.

    4: 2160p/4k, 3: 1080p, 2: 720p, 1: 480p/else, 0: 360p/240p.
    """
    if not quality_str:
        return 1

    q = quality_str.lower()
    if "2160" in q or "4k" in q:
        return 4
    if "1080" in q:
        return 3
    if "720" in q:
        return 2
    if "360" in q or "240" in q:
        return 0
    return 1


def select_best_result(
    results: Sequence[MovieResult | EpisodeResult],
) -> MovieResult | EpisodeResult | None:
    """Select the best result: highest quality first, then smallest size.

    Priority:
    1. Preferred Provider (if configured and found)
    2. Quality (Limit to max quality, 2160p > 1080p > 720p > 480p)
    3. Within same quality, prefer smaller file size
    """
    if not results:
        return None

    settings = get_settings()
    pref_provider = (
        settings.preferred_provider.lower() if settings.preferred_provider else None
    )
    q_limit = settings.quality_limit.lower() if settings.quality_limit else "2160p"

    limit_score = normalize_quality_score(q_limit)

    # Filter results by quality limit
    filtered_results = []
    for r in results:
        if normalize_quality_score(r.quality) <= limit_score:
            filtered_results.append(r)

    if not filtered_results:
        return None

    def score(result: MovieResult | EpisodeResult) -> tuple[int, int, int]:
        """Return (is_preferred, quality_score, -size) for sorting.

        Higher is_preferred is better.
        Higher quality score (up to limit) is better.
        Negative size means smaller files sort first when reversed.
        """
        is_pref = 0
        if pref_provider and result.provider_name:
            if result.provider_name.lower() == pref_provider:
                is_pref = 1

        q_score = normalize_quality_score(result.quality)

        return (is_pref, q_score, -result.size)

    # Sort and pick best from filtered results
    return max(filtered_results, key=score)
