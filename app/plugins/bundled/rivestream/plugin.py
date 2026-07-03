"""Rivestream provider"""

import logging
from cachetools import cached
import math
import base64
from niquests import Response
from typing import Any
import niquests
from cachetools import TTLCache
import asyncio
from typing import List

from app.providers.base import MovieResult, EpisodeResult
from app.plugins.base import PluginInterface
from app.models.media import Movie, TVSeries

logger = logging.getLogger(__name__)


RIVESTREAM_TIMEOUT = 20

cache = TTLCache(maxsize=100, ttl=1800)


class RiveSolver:
    KEY_FRAGMENTS = [
        "4Z7lUo",
        "gwIVSMD",
        "PLmz2elE2v",
        "Z4OFV0",
        "SZ6RZq6Zc",
        "zhJEFYxrz8",
        "FOm7b0",
        "axHS3q4KDq",
        "o9zuXQ",
        "4Aebt",
        "wgjjWwKKx",
        "rY4VIxqSN",
        "kfjbnSo",
        "2DyrFA1M",
        "YUixDM9B",
        "JQvgEj0",
        "mcuFx6JIek",
        "eoTKe26gL",
        "qaI9EVO1rB",
        "0xl33btZL",
        "1fszuAU",
        "a7jnHzst6P",
        "wQuJkX",
        "cBNhTJlEOf",
        "KNcFWhDvgT",
        "XipDGjST",
        "PCZJlbHoyt",
        "2AYnMZkqd",
        "HIpJh",
        "KH0C3iztrG",
        "W81hjts92",
        "rJhAT",
        "NON7LKoMQ",
        "NMdY3nsKzI",
        "t4En5v",
        "Qq5cOQ9H",
        "Y9nwrp",
        "VX5FYVfsf",
        "cE5SJG",
        "x1vj1",
        "HegbLe",
        "zJ3nmt4OA",
        "gt7rxW57dq",
        "clIE9b",
        "jyJ9g",
        "B5jXjMCSx",
        "cOzZBZTV",
        "FTXGy",
        "Dfh1q1",
        "ny9jqZ2POI",
        "X2NnMn",
        "MBtoyD",
        "qz4Ilys7wB",
        "68lbOMye",
        "3YUJnmxp",
        "1fv5Imona",
        "PlfvvXD7mA",
        "ZarKfHCaPR",
        "owORnX",
        "dQP1YU",
        "dVdkx",
        "qgiK0E",
        "cx9wQ",
        "5F9bGa",
        "7UjkKrp",
        "Yvhrj",
        "wYXez5Dg3",
        "pG4GMU",
        "MwMAu",
        "rFRD5wlM",
    ]

    @cached(cache)
    def solve(self, tmdb_id: str | int | None) -> str:
        if tmdb_id is None:
            return "rive"

        try:
            tmdb_id_str = str(tmdb_id)
            key_fragment = ""
            split_index = 0

            # Mimic JS Number() behavior
            # "" -> 0, "123" -> 123, "abc" -> NaN
            is_numeric = False
            numeric_val = float("nan")

            if tmdb_id == "":
                numeric_val = 0.0
                is_numeric = True
            else:
                try:
                    numeric_val = float(tmdb_id)
                    is_numeric = True
                except (ValueError, TypeError):
                    is_numeric = False

            if not is_numeric:
                # String path
                char_code_sum = sum(ord(c) for c in tmdb_id_str)
                key_fragment = self.KEY_FRAGMENTS[
                    char_code_sum % len(self.KEY_FRAGMENTS)
                ]
                if not key_fragment:
                    key_fragment = base64.b64encode(tmdb_id_str.encode()).decode()

                # split_index calculation
                if len(tmdb_id_str) > 0:
                    split_index = math.floor((char_code_sum % len(tmdb_id_str)) / 2)
                else:
                    split_index = 0
            else:
                # Number path
                i_val = int(numeric_val)
                key_fragment = self.KEY_FRAGMENTS[i_val % len(self.KEY_FRAGMENTS)]
                if not key_fragment:
                    key_fragment = base64.b64encode(tmdb_id_str.encode()).decode()

                if len(tmdb_id_str) > 0:
                    split_index = math.floor((i_val % len(tmdb_id_str)) / 2)
                else:
                    split_index = 0

            # Construct 'injected_str' (formerly 'i_str')
            injected_str = (
                tmdb_id_str[:split_index] + key_fragment + tmdb_id_str[split_index:]
            )

            # Inner function 2 (the complex mixing)
            mixed_result_1 = self._mix_step_2(injected_str)

            # Then run output = func1(mixed)
            final_mixed_result = self._mix_step_1(mixed_result_1)

            final_key = base64.b64encode(final_mixed_result.encode()).decode()
            return final_key

        except Exception:
            return "topSecret"

    def _to_js_hex(self, val: int) -> str:
        """
        Mimic JS .toString(16).padStart(8, "0") behavior on a 32-bit int.
        JS bitwise operators return signed 32-bit ints.
        """
        # Ensure val is treated as 32-bit unsigned first to match Python's stored state
        val &= 0xFFFFFFFF

        # Convert to signed 32-bit integer to match JS 'op' result
        if val >= 0x80000000:
            val -= 0x100000000

        # JS toString(16)
        if val < 0:
            s = "-" + hex(abs(val))[2:]
        else:
            s = hex(val)[2:]

        # padStart(8, "0")
        if len(s) < 8:
            s = "0" * (8 - len(s)) + s
        return s

    def _mix_step_2(self, input_str: str) -> str:
        # (function(e) {
        #     e = String(e);
        #     let t = 0;
        #     for (let n = 0; n < e.length; n++) {
        #         let r = e.charCodeAt(n)
        #           , i = (((t = (r + (t << 6) + (t << 16) - t) >>> 0) << (n % 5)) | (t >>> (32 - (n % 5)))) >>> 0;
        #         ((t ^= (i ^ ((r << (n % 7)) | (r >>> (8 - (n % 7))))) >>> 0),
        #         (t = (t + ((t >>> 11) ^ (t << 3))) >>> 0));
        #     }
        #     return ...
        # }

        # Renamed variables:
        # e -> input_str
        # t -> accumulator
        # n -> i (index)
        # r -> char_code

        input_str = str(input_str)
        accumulator = 0
        for i in range(len(input_str)):
            char_code = ord(input_str[i])
            # t = (r + (t << 6) + (t << 16) - t) >>> 0
            accumulator = (
                char_code + (accumulator << 6) + (accumulator << 16) - accumulator
            ) & 0xFFFFFFFF

            # i = ((t << (n % 5)) | (t >>> (32 - (n % 5)))) >>> 0
            # Python's >> is arithmetic, but for positive numbers it acts like logical.
            # We ensure t is unsigned 32-bit (positive) via the mask above.
            shift_amt = i % 5
            right_shift_amt = 32 - shift_amt
            rotation_val = (
                (accumulator << shift_amt) | (accumulator >> right_shift_amt)
            ) & 0xFFFFFFFF

            # t ^= (i ^ ((r << (n % 7)) | (r >>> (8 - (n % 7))))) >>> 0
            shift_r = i % 7
            right_shift_r = 8 - shift_r
            # r is 8-bit char code usually, but let's just do standard ops
            # (r >>> ...) in JS on a byte is just shift check.
            # But r is unicode code point.
            # In JS charCodeAt returns 0-65535.

            val_r = (
                (char_code << shift_r) | (char_code >> right_shift_r)
            ) & 0xFFFFFFFF  # JS >>> behaves weirdly if r is not u32? No r is small.
            # Wait, JS r >>> (8 - ...)
            # If r is small, r >> x is fine.

            accumulator = accumulator ^ (rotation_val ^ val_r)
            accumulator &= 0xFFFFFFFF

            # t = (t + ((t >>> 11) ^ (t << 3))) >>> 0
            accumulator = (
                accumulator + ((accumulator >> 11) ^ (accumulator << 3))
            ) & 0xFFFFFFFF

        # Return block
        # t ^= t >>> 15
        accumulator = (accumulator ^ (accumulator >> 15)) & 0xFFFFFFFF

        # t = ((65535 & t) * 49842 + ((((t >>> 16) * 49842) & 65535) << 16)) >>> 0
        # This is essentially integer multiplication simulation or just large constant mul logic
        # JS numbers are doubles, so bitwise ops force 32bit. Math is safe up to 2^53.
        # Python handles large ints automatically, so we just do the math and mask.

        # However, the JS code explicitly splits it:
        # t = ( (t & 0xFFFF) * 49842 + ( ((t >> 16) * 49842) & 0xFFFF ) << 16 )
        # This looks like it mimics 32-bit imul?
        # Actually (A + B) << 16 might overflow 32 bit so they split it.
        # In Python we can just do: t = (t * 49842) & 0xFFFFFFFF?
        # Let's stick to the structure to be safe against overflow wrapping in intermediate steps if JS does that.
        # But JS internal math is double.
        # (t & 0xFFFF) * 49842 is max 65535 * 49842 ≈ 3.2e9. fits in u32? No, 3.2 billion is > 2^31 but < 2^32.
        # The second part: ((t >> 16) * 49842) & 0xFFFF.  This masks the result to 16 bits.
        # Then << 16.
        # So it reconstructs the 32-bit result.

        term1 = (accumulator & 0xFFFF) * 49842
        term2 = (((accumulator >> 16) * 49842) & 0xFFFF) << 16
        accumulator = (term1 + term2) & 0xFFFFFFFF

        # t ^= t >>> 13
        accumulator = (accumulator ^ (accumulator >> 13)) & 0xFFFFFFFF

        # t = ((65535 & t) * 40503 + ((((t >>> 16) * 40503) & 65535) << 16)) >>> 0
        term1 = (accumulator & 0xFFFF) * 40503
        term2 = (((accumulator >> 16) * 40503) & 0xFFFF) << 16
        accumulator = (term1 + term2) & 0xFFFFFFFF

        # t ^= t >>> 16
        accumulator = (accumulator ^ (accumulator >> 16)) & 0xFFFFFFFF

        return self._to_js_hex(accumulator)

    def _mix_step_1(self, input_str: str) -> str:
        # (function(e) {
        #     let t = String(e)
        #       , n = 3735928559 ^ t.length;
        #     for (let e = 0; e < t.length; e++) {
        #         let r = t.charCodeAt(e);
        #         ((r ^= ((131 * e + 89) ^ (r << (e % 5))) & 255),
        #         (n = (((n << 7) | (n >>> 25)) >>> 0) ^ r));
        #         let i = (65535 & n) * 60205
        #           , o = ((n >>> 16) * 60205) << 16;
        #         ((n = (i + o) >>> 0),
        #         (n ^= n >>> 11));
        #     }
        #     return ...
        # }

        # Renamed variables:
        # e -> input_str
        # n -> hash_state
        # idx -> i
        # r -> char_code

        input_str = str(input_str)
        hash_state = 3735928559 ^ len(input_str)
        hash_state &= 0xFFFFFFFF

        for i in range(len(input_str)):
            char_code = ord(input_str[i])

            # r ^= ((131 * idx + 89) ^ (r << (idx % 5))) & 255
            val = (131 * i + 89) ^ (char_code << (i % 5))
            char_code = char_code ^ (val & 255)
            # r is now modified

            # n = (((n << 7) | (n >>> 25)) >>> 0) ^ r
            n_rot = ((hash_state << 7) | (hash_state >> 25)) & 0xFFFFFFFF
            hash_state = n_rot ^ char_code
            hash_state &= 0xFFFFFFFF

            # let i = (65535 & n) * 60205
            #   , o = ((n >>> 16) * 60205) << 16;
            term_i = (hash_state & 0xFFFF) * 60205
            term_o = ((hash_state >> 16) * 60205) << 16

            # n = (i + o) >>> 0
            hash_state = (term_i + term_o) & 0xFFFFFFFF

            # n ^= n >>> 11
            hash_state = (hash_state ^ (hash_state >> 11)) & 0xFFFFFFFF

        # Return block
        # n ^= n >>> 15
        hash_state = (hash_state ^ (hash_state >> 15)) & 0xFFFFFFFF

        # n = ((65535 & n) * 49842 + (((n >>> 16) * 49842) << 16)) >>> 0
        term1 = (hash_state & 0xFFFF) * 49842
        term2 = (
            (hash_state >> 16) * 49842
        ) << 16  # Note: JS code in mix_step_1 doesn't have & 65535 for term2 calc?
        # JS: ( (((n >>> 16) * 49842) << 16) )
        # In mix_step_2 it had: ((((t >>> 16) * 49842) & 65535) << 16)
        # Let's check original JS provided.
        # mix_step_1: (n = ((65535 & n) * 49842 + (((n >>> 16) * 49842) << 16)) >>> 0)
        # Yes, no & 65535 mask on the intermediate mul in step 1.

        hash_state = (term1 + term2) & 0xFFFFFFFF

        # n ^= n >>> 13
        hash_state = (hash_state ^ (hash_state >> 13)) & 0xFFFFFFFF

        # n = ((65535 & n) * 40503 + (((n >>> 16) * 40503) << 16)) >>> 0
        term1 = (hash_state & 0xFFFF) * 40503
        term2 = ((hash_state >> 16) * 40503) << 16
        hash_state = (term1 + term2) & 0xFFFFFFFF

        # n ^= n >>> 16
        hash_state = (hash_state ^ (hash_state >> 16)) & 0xFFFFFFFF

        # (n = ((65535 & n) * 10196 + (((n >>> 16) * 10196) << 16)) >>> 0)
        term1 = (hash_state & 0xFFFF) * 10196
        term2 = ((hash_state >> 16) * 10196) << 16
        hash_state = (term1 + term2) & 0xFFFFFFFF

        # n ^= n >>> 15
        hash_state = (hash_state ^ (hash_state >> 15)) & 0xFFFFFFFF

        return self._to_js_hex(hash_state)


class RiveStreamProvider(PluginInterface):
    """
    RiveStream Provider for https://www.rivestream.app/
    """

    def __init__(self):
        super().__init__()
        self.rive_solver = RiveSolver()

    @property
    def name(self) -> str:
        return "RiveStreamProvider"

    async def get_services(self) -> List[str]:
        """Return list of services.

        Fetches available video provider services from the Rivestream API.
        Returns cached results if available.  On any network, JSON, or
        schema error the failure is logged and an empty list is returned
        so that callers can degrade gracefully.
        """
        if "services" in cache:
            return cache["services"]

        try:
            response: Response = await self.session.get(
                "https://www.rivestream.app/api/backendfetch",
                params={
                    "requestID": "VideoProviderServices",
                    "secretKey": "rive",
                    "proxyMode": "noProxy",
                },
                timeout=RIVESTREAM_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            result = data["data"]

            if not isinstance(result, list):
                logger.warning(
                    "get_services: expected 'data' to be a list, got %s",
                    type(result).__name__,
                )
                return []

            cache["services"] = result
            return result
        except (KeyError, TypeError) as exc:
            logger.warning("get_services: unexpected response structure – %s", exc)
        except niquests.exceptions.RequestException as exc:
            logger.warning("get_services: network error – %s", exc)
        except (ValueError, UnicodeDecodeError) as exc:
            # ValueError covers json.JSONDecodeError (its subclass)
            logger.warning("get_services: failed to decode JSON – %s", exc)
        except Exception as exc:
            logger.warning("get_services: unexpected error – %s", exc)

        return []

    async def get_movies_with_service(
        self, movie: Movie, service: str
    ) -> List[MovieResult]:
        """Return list of movies with a service."""
        cache_key = f"movies-{movie.id}-{service}"
        if cache_key in cache:
            return cache[cache_key]

        params = {
            "requestID": "movieVideoProvider",
            "id": movie.id,
            "service": service,
            "secretKey": self.rive_solver.solve(movie.id),
            "proxyMode": "noProxy",
        }

        try:
            response: Response = await self.session.get(
                "https://www.rivestream.app/api/backendfetch",
                params=params,
                timeout=RIVESTREAM_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (niquests.exceptions.RequestException, ValueError) as exc:
            logger.warning("get_movies_with_service error for %s: %s", service, exc)
            return []

        if "data" not in payload:
            return []

        data = payload["data"]
        if (
            data is None
            or "sources" not in data
            or not isinstance(data["sources"], list)
        ):
            return []

        sources = data["sources"]
        movies = []
        for source in sources:
            url = source.get("url")
            quality = source.get("quality")
            fmt = source.get("format")

            if url is None or quality is None or fmt is None:
                continue

            movies.append(
                MovieResult(
                    provider_name=self.name,
                    title=movie.title,
                    download_url=url,
                    quality=f"{quality}p-{fmt}",
                    size=source.get("size", 0),
                    source_site=self.name,
                    filename=f"{movie.title} - {quality}p - {service}.{fmt}",
                )
            )

        cache[cache_key] = movies
        return movies

    async def get_movie_from_all_services(self, movie: Movie) -> List[MovieResult]:
        """Return list of movies from all services."""
        services = await self.get_services()

        tasks = [self.get_movies_with_service(movie, service) for service in services]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        movies = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "get_movie_from_all_services: error fetching from service – %s",
                    result,
                )
                continue
            if result:
                movies.extend(result)
        return movies

    async def get_movie(self, movie: Movie) -> List[MovieResult]:
        """Return dummy movie download links."""

        return await self.get_movie_from_all_services(movie)

    async def get_series_episode_with_service(
        self, series: TVSeries, season: int, episode: int, service: str
    ) -> List[EpisodeResult]:
        """Return list of episodes with a service."""
        cache_key = f"series-{series.id}-s{season}-e{episode}-{service}"
        if cache_key in cache:
            return cache[cache_key]

        params = {
            "requestID": "tvVideoProvider",
            "id": series.id,
            "season": season,
            "episode": episode,
            "service": service,
            "secretKey": self.rive_solver.solve(series.id),
            "proxyMode": "noProxy",
        }
        response = None
        try:
            response = await self.session.get(
                "https://www.rivestream.app/api/backendfetch",
                params=params,
                timeout=RIVESTREAM_TIMEOUT,
            )
            response.raise_for_status()
            json_data = response.json()
        except (niquests.exceptions.RequestException, ValueError) as exc:
            resp_text = response.text if response else "N/A"
            logger.warning(
                "get_series_episode_with_service error for %s: %s. Response: %s",
                service,
                exc,
                resp_text,
                exc_info=exc,
            )
            return []

        if "error" in json_data:
            return []
        data = json_data.get("data")
        if data is None or "sources" not in data:
            return []
        sources = data["sources"]
        episodes = []
        for source in sources:
            url = source.get("url")
            quality = source.get("quality")
            fmt = source.get("format")

            if not url or not quality or not fmt:
                continue

            size = source.get("size", 0)
            episodes.append(
                EpisodeResult(
                    provider_name=self.name,
                    title=f"{series.title} S{season:02d}E{episode:02d}",
                    season=season,
                    episode=episode,
                    download_url=url,
                    quality=f"{quality}p-{fmt}",
                    size=size,
                    source_site=self.name,
                    filename=f"{series.title} S{season:02d}E{episode:02d} - {quality}p - {service}.{fmt}",
                )
            )
        cache[cache_key] = episodes
        return episodes

    async def get_series_episode_from_all_services(
        self, series: TVSeries, season: int, episode: int
    ) -> List[EpisodeResult]:
        """Return list of episodes from all services."""
        services = await self.get_services()

        tasks = [
            self.get_series_episode_with_service(series, season, episode, service)
            for service in services
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        episodes = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "get_series_episode_from_all_services: error fetching from service – %s",
                    result,
                )
                continue
            if result:
                episodes.extend(result)
        return episodes

    async def get_series_episode(
        self,
        series: TVSeries,
        season: int,
        episode: int,
    ) -> List[EpisodeResult]:
        """Return episode download links from all services."""
        return await self.get_series_episode_from_all_services(series, season, episode)

    def get_yt_opts(self) -> dict[str, Any]:
        opts = super().get_yt_opts()
        headers = opts.get("http_headers", {})
        headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://www.rivestream.app/",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        opts["http_headers"] = headers
        return opts
