"""AIOStreams provider."""

import logging
import re
from typing import Any, ClassVar
from urllib.parse import urlparse

from pydantic import field_validator

from app.models.media import Movie, TVSeries
from app.providers.base import EpisodeResult, MovieResult
from app.plugins.base import PluginConfig, PluginInterface

logger = logging.getLogger(__name__)


class AIOStreamsConfig(PluginConfig):
    """Configuration for the AIOStreams plugin."""

    manifest_url: str

    @field_validator("manifest_url")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("manifest_url must not be empty")
        return v


class AIOStreamsProvider(PluginInterface):
    """AIOStreams provider implementation."""

    config_model: ClassVar[type[PluginConfig]] = AIOStreamsConfig

    @property
    def name(self) -> str:
        return "AIOStreams"

    def _parse_manifest_url(self) -> tuple[str, str, str] | None:
        """Parse manifest URL to extract base_url, uuid, and encrypted_password.

        Expected format:
            https://{base_url}/stremio/{uuid}/{encrypted_password}/manifest.json
        """
        if not self.config or not self.config.manifest_url:
            return None

        url = self.config.manifest_url.rstrip("/")
        parsed = urlparse(url)
        path = parsed.path

        # Match /stremio/{uuid}/{encrypted_password}/manifest.json
        match = re.match(
            r"^/stremio/([a-f0-9-]+)/(.+)/manifest\.json$", path
        )
        if not match:
            raise ValueError(
                f"Invalid AIOStreams manifest URL format: {url}. "
                "Expected: https://<base>/stremio/<uuid>/<encrypted_password>/manifest.json"
            )

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        uuid = match.group(1)
        encrypted_password = match.group(2)
        return base_url, uuid, encrypted_password

    async def _get_streams(self, type: str, id: str) -> list[dict[str, Any]]:
        """Fetch streams from the AIOStreams Stremio endpoint."""
        parsed = self._parse_manifest_url()
        if not parsed:
            raise ValueError(
                "AIOStreams manifest_url is not configured. "
                "Set it in the plugin's config.json."
            )

        base_url, uuid, encrypted_password = parsed
        stream_url = f"{base_url}/stremio/{uuid}/{encrypted_password}/stream/{type}/{id}.json"

        try:
            response = await self.session.get(stream_url, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data.get("streams", [])
        except Exception:
            logger.exception("Error fetching AIOStreams streams for %s/%s", type, id)
            return []

    def _extract_quality(self, text: str, default: str = "Unknown") -> str:
        """Extract quality string from stream name or description."""
        text = text.lower()
        if "2160p" in text or "4k" in text:
            return "2160p"
        if "1080p" in text or "1080" in text:
            return "1080p"
        if "720p" in text or "720" in text:
            return "720p"
        if "480p" in text or "480" in text:
            return "480p"
        if "360p" in text or "360" in text:
            return "360p"
        return default

    def _quality_rank(self, quality: str) -> int:
        """Assign an integer rank to a quality string for sorting."""
        q = quality.lower()
        if "2160" in q or "4k" in q:
            return 2160
        if "1080" in q:
            return 1080
        if "720" in q:
            return 720
        if "480" in q:
            return 480
        if "360" in q:
            return 360
        return 0

    def _get_stream_size(self, stream: dict[str, Any]) -> int:
        """Extract file size from stream data.

        Some addons report folder/season size instead of file size.
        Parse from description as fallback. If description shows
        "file_size/folder_size" pattern, use the file size.
        """
        hints = stream.get("behaviorHints", {})
        desc = stream.get("description", "")

        # Try videoSize first (only if reasonable for a single file)
        MAX_SINGLE_FILE_SIZE = 20 * 1024 * 1024 * 1024  # 20 GB
        size = hints.get("videoSize")
        if isinstance(size, (int, float)) and 0 < size <= MAX_SINGLE_FILE_SIZE:
            return int(size)

        # Parse from description
        # Pattern 1: "X GB/Y GB" or "X MB/Y GB" (file/folder)
        match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|TB)\s*/\s*\d+", desc, re.IGNORECASE)
        if match:
            return self._parse_size(match.group(1), match.group(2))

        # Pattern 2: "X GB" or "X MB" (single size)
        match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|TB)", desc, re.IGNORECASE)
        if match:
            return self._parse_size(match.group(1), match.group(2))

        return 0

    def _parse_size(self, value: str, unit: str) -> int:
        """Convert size string to bytes."""
        multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
        return int(float(value) * multipliers.get(unit.upper(), 0))

    def _get_filename(self, stream: dict[str, Any], default: str) -> str:
        """Extract filename from stream data."""
        hints = stream.get("behaviorHints", {})
        return hints.get("filename") or default

    def _sanitize_filename(self, name: str) -> str:
        """Strip invalid characters from filenames."""
        return re.sub(r'[<>:"/\\|?*]', "", name).strip()

    def _has_usable_streams(self, streams: list[dict[str, Any]]) -> bool:
        """Check if any streams have a download URL."""
        return any(s.get("url") for s in streams)

    async def get_movie(self, movie: Movie) -> list[MovieResult]:
        """Get download links for a movie."""
        # Try tmdb ID first
        streams = await self._get_streams("movie", f"tmdb:{movie.id}")

        # Fallback to IMDB ID if no results
        if not self._has_usable_streams(streams) and movie.imdb_id:
            imdb_id = movie.imdb_id if movie.imdb_id.startswith("tt") else f"tt{movie.imdb_id}"
            streams = await self._get_streams("movie", imdb_id)
        results: list[MovieResult] = []

        for stream in streams:
            url = stream.get("url")
            if not url:
                continue

            stream_name = stream.get("name") or stream.get("description") or ""
            quality = self._extract_quality(stream_name)
            size = self._get_stream_size(stream)
            filename = self._get_filename(
                stream, f"{self._sanitize_filename(movie.title)} - {quality}.mp4"
            )

            results.append(
                MovieResult(
                    title=movie.title,
                    quality=quality,
                    size=size,
                    download_url=url,
                    source_site=self.name,
                    provider_name=self.name,
                    filename=filename,
                )
            )

        results.sort(
            key=lambda r: self._quality_rank(r.quality), reverse=True
        )
        return results

    async def get_series_episode(
        self,
        series: TVSeries,
        season: int,
        episode: int,
    ) -> list[EpisodeResult]:
        """Get download links for a TV episode."""
        # Try tmdb ID first
        streams = await self._get_streams("series", f"tmdb:{series.id}:{season}:{episode}")

        # Fallback to IMDB ID if no results
        if not self._has_usable_streams(streams) and series.imdb_id:
            imdb_id = series.imdb_id if series.imdb_id.startswith("tt") else f"tt{series.imdb_id}"
            streams = await self._get_streams("series", f"{imdb_id}:{season}:{episode}")
        results: list[EpisodeResult] = []

        for stream in streams:
            url = stream.get("url")
            if not url:
                continue

            stream_name = stream.get("name") or stream.get("description") or ""
            quality = self._extract_quality(stream_name)
            size = self._get_stream_size(stream)
            filename = self._get_filename(
                stream,
                f"{self._sanitize_filename(series.title)}.S{season:02d}E{episode:02d}.mp4",
            )

            results.append(
                EpisodeResult(
                    title=f"{series.title} S{season:02d}E{episode:02d}",
                    season=season,
                    episode=episode,
                    quality=quality,
                    size=size,
                    download_url=url,
                    source_site=self.name,
                    provider_name=self.name,
                    filename=filename,
                )
            )

        results.sort(
            key=lambda r: self._quality_rank(r.quality), reverse=True
        )
        return results
