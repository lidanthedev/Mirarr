"""AIOStreams provider."""

import logging
import re
from typing import Any, ClassVar
from urllib.parse import urlparse

from app.models.media import Movie, TVSeries
from app.providers.base import EpisodeResult, MovieResult
from app.plugins.base import PluginConfig, PluginInterface

logger = logging.getLogger(__name__)


class AIOStreamsConfig(PluginConfig):
    """Configuration for the AIOStreams plugin."""

    manifest_url: str = ""


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
        """Extract file size from stream data."""
        hints = stream.get("behaviorHints", {})
        size = hints.get("videoSize")
        if isinstance(size, (int, float)) and size > 0:
            return int(size)
        return 0

    def _get_filename(self, stream: dict[str, Any], default: str) -> str:
        """Extract filename from stream data."""
        hints = stream.get("behaviorHints", {})
        return hints.get("filename") or default

    def _sanitize_filename(self, name: str) -> str:
        """Strip invalid characters from filenames."""
        return re.sub(r'[<>:"/\\|?*]', "", name).strip()

    async def get_movie(self, movie: Movie) -> list[MovieResult]:
        """Get download links for a movie."""
        if movie.imdb_id:
            stream_id = f"tt{movie.imdb_id}"
        else:
            stream_id = f"tmdb:{movie.id}"

        streams = await self._get_streams("movie", stream_id)
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
        stream_id = f"tmdb:{series.id}:{season}:{episode}"

        streams = await self._get_streams("series", stream_id)
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
