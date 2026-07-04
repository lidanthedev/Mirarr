"""TMDB service for searching and fetching movie/series details."""

import asyncio
from cachetools import cached
from cachetools import TTLCache
from typing import List, Optional
from enum import Enum

import tmdbsimple as tmdb
from pydantic import BaseModel

from app.core.config import get_settings
from app.models.media import Movie, TVSeries, Season, Episode
import logging
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class TMDBError(Exception):
    """Domain exception for TMDB failures."""

    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(message)
        self.original_exception = original_exception


movie_cache = TTLCache(maxsize=100, ttl=1800)
series_cache = TTLCache(maxsize=100, ttl=1800)

movie_cache_lock = threading.Lock()
series_cache_lock = threading.Lock()

# Initialize TMDB
settings = get_settings()
tmdb.API_KEY = settings.tmdb_api_key


class MediaType(str, Enum):
    """Media type for search."""

    MOVIE = "movie"
    SERIES = "tv"
    ALL = "all"


class TMDBSearchResult(BaseModel):
    """A search result from TMDB (lightweight for grid display)."""

    id: int
    title: str
    overview: str
    poster_url: Optional[str]
    backdrop_url: Optional[str]
    media_type: MediaType
    release_year: Optional[str]
    vote_average: float = 0.0


def _parse_movie_search(movie: dict) -> TMDBSearchResult:
    """Parse a movie search result from TMDB."""
    poster_path = movie.get("poster_path")
    backdrop_path = movie.get("backdrop_path")
    release_date = movie.get("release_date", "")

    return TMDBSearchResult(
        id=movie["id"],
        title=movie.get("title", "Unknown"),
        overview=movie.get("overview", ""),
        poster_url=f"https://image.tmdb.org/t/p/w500{poster_path}"
        if poster_path
        else None,
        backdrop_url=f"https://image.tmdb.org/t/p/w780{backdrop_path}"
        if backdrop_path
        else None,
        media_type=MediaType.MOVIE,
        release_year=release_date[:4] if release_date else None,
        vote_average=movie.get("vote_average", 0.0),
    )


def _parse_series_search(series: dict) -> TMDBSearchResult:
    """Parse a TV series search result from TMDB."""
    poster_path = series.get("poster_path")
    backdrop_path = series.get("backdrop_path")
    first_air_date = series.get("first_air_date", "")

    return TMDBSearchResult(
        id=series["id"],
        title=series.get("name", "Unknown"),
        overview=series.get("overview", ""),
        poster_url=f"https://image.tmdb.org/t/p/w500{poster_path}"
        if poster_path
        else None,
        backdrop_url=f"https://image.tmdb.org/t/p/w780{backdrop_path}"
        if backdrop_path
        else None,
        media_type=MediaType.SERIES,
        release_year=first_air_date[:4] if first_air_date else None,
        vote_average=series.get("vote_average", 0.0),
    )


def _search_movies_sync(query: str) -> List[TMDBSearchResult]:
    """Search TMDB for movies (synchronous)."""
    search = tmdb.Search()
    try:
        search.movie(query=query)
        return [_parse_movie_search(m) for m in search.results[:12]]
    except (requests.exceptions.RequestException, tmdb.APIKeyError) as exc:
        logger.error("Error searching movies for '%s': %s", query, exc)
        return []
    except Exception as exc:
        logger.exception("Unexpected error searching movies for '%s': %s", query, exc)
        return []


async def search_movies(query: str) -> List[TMDBSearchResult]:
    """Search TMDB for movies (async)."""
    return await asyncio.to_thread(_search_movies_sync, query)


def _search_series_sync(query: str) -> List[TMDBSearchResult]:
    """Search TMDB for TV series (synchronous)."""
    search = tmdb.Search()
    try:
        search.tv(query=query)
        return [_parse_series_search(s) for s in search.results[:12]]
    except (requests.exceptions.RequestException, tmdb.APIKeyError) as exc:
        logger.error("Error searching series for '%s': %s", query, exc)
        return []
    except Exception as exc:
        logger.exception("Unexpected error searching series for '%s': %s", query, exc)
        return []


async def search_series(query: str) -> List[TMDBSearchResult]:
    """Search TMDB for TV series (async)."""
    return await asyncio.to_thread(_search_series_sync, query)


def _search_all_sync(query: str) -> List[TMDBSearchResult]:
    """Search TMDB for both movies and TV series (synchronous)."""
    search = tmdb.Search()
    try:
        search.multi(query=query)
        results = []
        for item in search.results[:12]:
            media_type = item.get("media_type")
            if media_type == "movie":
                results.append(_parse_movie_search(item))
            elif media_type == "tv":
                results.append(_parse_series_search(item))
            # Skip "person" results
        return results
    except (requests.exceptions.RequestException, tmdb.APIKeyError) as exc:
        logger.error("Error searching all for '%s': %s", query, exc)
        return []
    except Exception as exc:
        logger.exception("Unexpected error searching all for '%s': %s", query, exc)
        return []


async def search_all(query: str) -> List[TMDBSearchResult]:
    """Search TMDB for both movies and TV series (async)."""
    return await asyncio.to_thread(_search_all_sync, query)


async def search_tmdb(
    query: str, media_type: MediaType = MediaType.ALL
) -> List[TMDBSearchResult]:
    """Search TMDB based on media type."""
    if media_type == MediaType.MOVIE:
        return await search_movies(query)
    elif media_type == MediaType.SERIES:
        return await search_series(query)
    else:
        return await search_all(query)


@cached(movie_cache, lock=movie_cache_lock)
def _get_movie_details_sync(tmdb_id: int) -> Movie:
    """Fetch full movie details from TMDB (synchronous, cached)."""
    movie_api = tmdb.Movies(tmdb_id)
    try:
        info = movie_api.info()
    except Exception as exc:
        logger.error("Failed to fetch movie details for ID %s: %s", tmdb_id, exc)
        raise TMDBError(f"Failed to fetch movie details for ID {tmdb_id}", exc) from exc

    poster_path = info.get("poster_path")
    backdrop_path = info.get("backdrop_path")
    release_date = info.get("release_date", "")

    return Movie(
        id=info["id"],
        title=info.get("title", "Unknown"),
        overview=info.get("overview", ""),
        poster_url=f"https://image.tmdb.org/t/p/w500{poster_path}"
        if poster_path
        else None,
        backdrop_url=f"https://image.tmdb.org/t/p/w780{backdrop_path}"
        if backdrop_path
        else None,
        release_date=release_date,
        release_year=release_date[:4] if release_date else None,
        vote_average=info.get("vote_average", 0.0),
        runtime=info.get("runtime"),
        genres=[g["name"] for g in info.get("genres", [])],
        imdb_id=info.get("imdb_id"),
    )


async def get_movie_details(tmdb_id: int) -> Movie:
    """Fetch full movie details from TMDB (async)."""
    return await asyncio.to_thread(_get_movie_details_sync, tmdb_id)


def _get_season_episodes_sync(tmdb_id: int, season_number: int) -> List[Episode]:
    """Fetch episodes for a specific season (synchronous)."""
    season_api = tmdb.TV_Seasons(tmdb_id, season_number)
    try:
        info = season_api.info()
    except Exception as exc:
        logger.error(
            "Failed to fetch season episodes for ID %s S%s: %s",
            tmdb_id,
            season_number,
            exc,
        )
        raise TMDBError(
            f"Failed to fetch season episodes for ID {tmdb_id} S{season_number}", exc
        ) from exc

    episodes = []
    for ep in info.get("episodes", []):
        episodes.append(
            Episode(
                episode_number=ep["episode_number"],
                name=ep.get("name", f"Episode {ep['episode_number']}"),
                overview=ep.get("overview", ""),
                air_date=ep.get("air_date"),
                runtime=ep.get("runtime"),
            )
        )

    return episodes


@cached(series_cache, lock=series_cache_lock)
def _get_series_details_sync(tmdb_id: int) -> TVSeries:
    """Fetch full TV series details from TMDB including seasons and episodes (synchronous, cached)."""
    tv_api = tmdb.TV(tmdb_id)
    try:
        info = tv_api.info(append_to_response="external_ids")
    except Exception as exc:
        logger.error("Failed to fetch series details for ID %s: %s", tmdb_id, exc)
        raise TMDBError(
            f"Failed to fetch series details for ID {tmdb_id}", exc
        ) from exc

    poster_path = info.get("poster_path")
    backdrop_path = info.get("backdrop_path")
    first_air_date = info.get("first_air_date", "")

    # Parse seasons (excluding specials - season 0) and fetch episodes for each
    seasons = []
    season_data_list = [
        s for s in info.get("seasons", []) if s.get("season_number", 0) > 0
    ]

    # Fetch episodes concurrently
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_season = {
            executor.submit(_get_season_episodes_sync, tmdb_id, s["season_number"]): s
            for s in season_data_list
        }

        season_episodes_map = {}
        for future in as_completed(future_to_season):
            s = future_to_season[future]
            sn = s["season_number"]
            try:
                episodes = future.result()
                season_episodes_map[sn] = episodes
            except Exception as exc:
                logger.error(
                    "Failed to fetch episodes for season %s of show %s: %s",
                    sn,
                    tmdb_id,
                    exc,
                )
                season_episodes_map[sn] = []

    # Build Season objects in order
    for s in season_data_list:
        sn = s["season_number"]
        episodes = season_episodes_map.get(sn, [])
        seasons.append(
            Season(
                season_number=sn,
                name=s.get("name", f"Season {sn}"),
                episode_count=s.get("episode_count", 0),
                air_date=s.get("air_date"),
                overview=s.get("overview", ""),
                episodes=episodes,
            )
        )

    return TVSeries(
        id=info["id"],
        title=info.get("name", "Unknown"),
        overview=info.get("overview", ""),
        poster_url=f"https://image.tmdb.org/t/p/w500{poster_path}"
        if poster_path
        else None,
        backdrop_url=f"https://image.tmdb.org/t/p/w780{backdrop_path}"
        if backdrop_path
        else None,
        first_air_date=first_air_date,
        release_year=first_air_date[:4] if first_air_date else None,
        vote_average=info.get("vote_average", 0.0),
        number_of_seasons=info.get("number_of_seasons", 0),
        number_of_episodes=info.get("number_of_episodes", 0),
        seasons=seasons,
        genres=[g["name"] for g in info.get("genres", [])],
        status=info.get("status", ""),
        imdb_id=info.get("external_ids", {}).get("imdb_id"),
    )


async def get_series_details(tmdb_id: int) -> TVSeries:
    """Fetch full TV series details from TMDB including seasons and episodes (async)."""
    return await asyncio.to_thread(_get_series_details_sync, tmdb_id)


async def get_season_episodes(tmdb_id: int, season_number: int) -> List[Episode]:
    """Fetch episodes for a specific season (async)."""
    return await asyncio.to_thread(_get_season_episodes_sync, tmdb_id, season_number)
