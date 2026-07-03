"""AcerMovies provider."""

import logging
import re
from typing import Any, ClassVar
from urllib.parse import unquote

from aiolimiter import AsyncLimiter
from cachetools import TTLCache

from app.models.media import Movie, TVSeries
from app.providers.base import EpisodeResult, MovieResult
from app.plugins.base import PluginInterface

logger = logging.getLogger(__name__)


class AcerMoviesProvider(PluginInterface):
    """AcerMovies provider implementation."""

    API_BASE_URL = "https://api.acermovies.fun/api"
    DEFAULT_HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://acermovies.fun/",
        "Origin": "https://acermovies.fun",
    }

    @property
    def name(self) -> str:
        return "AcerMovies"

    def __init__(self) -> None:
        super().__init__()
        self.rate_limiter: AsyncLimiter = AsyncLimiter(5, 60.0)
        self.cache: TTLCache = TTLCache(maxsize=100, ttl=1800)

    def _sanitize_filename(self, name: str) -> str:
        """Strip invalid characters from filenames and trim whitespace."""
        return re.sub(r'[<>:"/\\|?*]', "", name).strip()

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Helper to perform POST requests with retries."""
        url = f"{self.API_BASE_URL}/{endpoint}"
        try:
            async with self.rate_limiter:
                response = await self.session.post(
                    url, json=payload, headers=self.DEFAULT_HEADERS, timeout=10
                )
                response.raise_for_status()
                return response.json()
        except Exception:
            logger.exception("Error requesting %s", endpoint)
            return {}

    async def _search(self, query: str) -> list[dict[str, Any]]:
        """Search for content on AcerMovies."""
        cache_key = f"search_{query}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = await self._post("search", {"searchQuery": query})
        results = data.get("searchResult", [])

        if results:
            self.cache[cache_key] = results
        return results

    async def _get_qualities(self, movie_url: str) -> list[dict[str, Any]]:
        """Get available qualities for a movie."""
        cache_key = f"qualities:{movie_url}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = await self._post("sourceQuality", {"url": movie_url})
        qualities = data.get("sourceQualityList", [])
        if qualities:
            self.cache[cache_key] = qualities
        return qualities

    async def _get_episodes(self, episodes_api_url: str) -> list[dict[str, Any]]:
        """Get episodes or seasons given a URL."""
        cache_key = f"episodes:{episodes_api_url}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = await self._post("sourceEpisodes", {"url": episodes_api_url})
        episodes = data.get("sourceEpisodes", [])

        if not isinstance(episodes, list):
            logger.warning("Expected list for episodes, got %s", type(episodes))
            return []

        if episodes:
            self.cache[cache_key] = episodes
        return episodes

    async def _get_source_url(
        self, source_api_url: str, series_type: str = "movie"
    ) -> str | None:
        """Get the final direct download URL."""
        # Not caching final URLs as they might expire or be one-time tokens
        data = await self._post(
            "sourceUrl", {"url": source_api_url, "seriesType": series_type}
        )
        source_url = data.get("sourceUrl")
        if source_url:
            return unquote(source_url)
        return None

    def _quality_rank(self, quality: str) -> int:
        """Assign an integer rank to a quality string for sorting."""
        q = quality.lower()
        if "2160" in q or "4k" in q or "uhd" in q:
            return 4000
        if "1080" in q or "fhd" in q:
            return 1080
        if "720" in q or re.search(r"\bhd\b", q):
            return 720
        if "480" in q or "sd" in q:
            return 480
        if "360" in q:
            return 360
        return 0

    def _extract_quality(self, text: str, default: str = "Unknown") -> str:
        """Attempt to extract standard quality strings from text."""
        text = text.lower()
        if "2160p" in text or "4k" in text:
            return "2160p"
        if "1080p" in text or "1080" in text:
            return "1080p"
        if "720p" in text or "720" in text:
            return "720p"
        if "480p" in text or "480" in text:
            return "480p"
        return default

    async def get_movie(self, movie: Movie) -> list[MovieResult]:
        """Get download links for a movie."""
        search_results = await self._search(movie.title)
        results = []

        for result in search_results:
            result_title = result.get("title", "")
            if movie.title.lower() not in result_title.lower():
                continue

            result_year = result.get("year")
            if (
                result_year
                and movie.release_year
                and str(result_year) != str(movie.release_year)
            ):
                continue

            movie_url = result.get("url")
            if not movie_url:
                continue

            qualities = await self._get_qualities(movie_url)
            # Sort qualities by resolution descending
            qualities.sort(
                key=lambda x: self._quality_rank(x.get("quality", "")), reverse=True
            )
            qualities = qualities[:2]  # Limit to 2 best qualities
            for q in qualities:
                quality_str = q.get("quality", "Unknown")
                source_api_url = q.get("url")
                if not source_api_url:
                    continue

                final_url = await self._get_source_url(
                    source_api_url, series_type="movie"
                )
                if not final_url:
                    continue

                results.append(
                    MovieResult(
                        title=movie.title,
                        quality=quality_str,
                        size=0,
                        download_url=final_url,
                        source_site=self.name,
                        provider_name=self.name,
                        filename=f"{self._sanitize_filename(movie.title)} - {quality_str}.mp4",
                    )
                )

        return results

    async def get_series_episode(
        self,
        series: TVSeries,
        season: int,
        episode: int,
    ) -> list[EpisodeResult]:
        """Get download links for a TV episode."""
        search_results = await self._search(series.title)
        results = []

        for result in search_results:
            result_title = result.get("title", "")
            if series.title.lower() not in result_title.lower():
                continue

            episodes_api_url = result.get("url")
            if not episodes_api_url:
                continue

            # Get the top-level list (Seasons/Qualities containers)
            try:
                containers = await self._get_episodes(episodes_api_url)
            except Exception:
                logger.exception(
                    "Error getting episodes for container %s", episodes_api_url
                )
                continue

            # Filter for likely season containers (Episode Links or Season X)
            season_containers = [
                c
                for c in containers
                if (
                    "Episode Links" in c.get("title", "")
                    or "Season" in c.get("title", "")
                )
                and "Batch" not in c.get("title", "")
            ]

            if not season_containers:
                continue

            indices_to_check = []
            season_str_1 = f"season {season}"
            season_str_2 = f"s{season:02d}"

            for idx, c in enumerate(season_containers):
                c_title = c.get("title", "").lower()
                if season_str_1 in c_title or season_str_2 in c_title:
                    indices_to_check.append(idx)

            # Fallback to original arithmetic indexing if no title matches
            if not indices_to_check:
                num_seasons = series.number_of_seasons or 1
                if num_seasons < 1:
                    num_seasons = 1
                curr_idx = season - 1
                while curr_idx < len(season_containers):
                    indices_to_check.append(curr_idx)
                    curr_idx += num_seasons

            for idx in indices_to_check:
                container = season_containers[idx]
                ep_link = container.get("link")
                if not ep_link:
                    continue

                try:
                    episodes_list = await self._get_episodes(ep_link)
                except Exception:
                    logger.exception("Error getting episode list from link %s", ep_link)
                    continue

                for ep_data in episodes_list:
                    ep_title = ep_data.get("title", "")

                    match = re.search(
                        r"(?:episode|ep)\s*(\d+)", ep_title, re.IGNORECASE
                    )
                    if match:
                        ep_num_str = match.group(1)
                    else:
                        matches = re.findall(r"\d+", ep_title)
                        ep_num_str = matches[-1] if matches else ""

                    if ep_num_str.isdigit() and int(ep_num_str) == episode:
                        source_api_url = ep_data.get("link") or ep_data.get("url")
                        if not source_api_url:
                            continue

                        final_url = await self._get_source_url(
                            source_api_url, series_type="episode"
                        )
                        if not final_url:
                            continue

                        # Extract quality from the container title if possible
                        container_title = container.get("title", "")
                        quality_str = self._extract_quality(container_title)

                        results.append(
                            EpisodeResult(
                                title=f"{series.title} S{season:02d}E{episode:02d}",
                                season=season,
                                episode=episode,
                                quality=quality_str,
                                size=0,
                                download_url=final_url,
                                source_site=self.name,
                                provider_name=self.name,
                                filename=f"{self._sanitize_filename(series.title)}.S{season:02d}E{episode:02d}.mp4",
                            )
                        )

        return results

    def get_yt_opts(self) -> dict[str, Any]:
        opts = super().get_yt_opts()
        headers = opts.get("http_headers", {})
        headers.update(self.DEFAULT_HEADERS)
        opts["http_headers"] = headers
        return opts
