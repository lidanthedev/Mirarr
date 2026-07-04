"""Media models for caching TMDB data."""

from typing import List, Optional
from pydantic import BaseModel


class Episode(BaseModel):
    """An episode in a TV series."""

    episode_number: int
    name: str
    overview: str = ""
    air_date: Optional[str] = None
    runtime: Optional[int] = None


class Season(BaseModel):
    """A season of a TV series."""

    season_number: int
    name: str
    episode_count: int
    episodes: List[Episode] = []
    air_date: Optional[str] = None
    overview: str = ""


class Movie(BaseModel):
    """A movie with full TMDB data."""

    id: int
    title: str
    overview: str = ""
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    release_date: Optional[str] = None
    release_year: Optional[str] = None
    vote_average: float = 0.0
    runtime: Optional[int] = None
    genres: List[str] = []
    imdb_id: Optional[str] = None


class TVSeries(BaseModel):
    """A TV series with full TMDB data including seasons."""

    id: int
    title: str
    overview: str = ""
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    first_air_date: Optional[str] = None
    release_year: Optional[str] = None
    vote_average: float = 0.0
    number_of_seasons: int = 0
    number_of_episodes: int = 0
    seasons: List[Season] = []
    genres: List[str] = []
    status: str = ""  # e.g., "Returning Series", "Ended"
    imdb_id: Optional[str] = None
