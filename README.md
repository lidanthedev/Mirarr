# Mirrarr

A "Sonarr-like" personal video recorder (PVR) for Direct Download (DDL) content. Mirrarr allows you to search for Movies and TV Shows using metadata from TMDB, find download links from various providers, and download them using `yt-dlp`.

## Features
- **Search**: Integrated with TMDB for rich metadata.
- **Modular Providers**: Easily extensible architecture for adding new DDL sources.
- **Smart Downloading**: Auto-selects the best quality release or allows manual selection.
- **Background Downloading**: Asynchronous download queue management.
- **Modern UI**: Built with FastAPI, Jinja2, HTMX, and TailwindCSS.

## Installation & Running

### Option 1: Docker (Recommended)

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/lidanthedev/Mirrarr.git
    cd Mirrarr
    ```

2.  **Configure Environment**:
    Create a `.env` file in the root directory. You can use `.env.example` as a template if available.
    Required variables:
    ```env
    TMDB_API_KEY=your_tmdb_api_key_here # Get one at https://www.themoviedb.org/settings/api
    AUTH_USERNAME=admin
    AUTH_PASSWORD=changeme
    ```

3.  **Run with Docker Compose**:
    ```bash
    docker compose up --build
    ```
    The application will be available at `http://localhost:8000`.

### Option 2: Development (uv)

Mirrarr uses `uv` for fast package management and virtual environment handling.

1.  **Install `uv`** (if not already installed):
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

2.  **Install Dependencies**:
    ```bash
    uv sync
    ```

3.  **Run Development Server**:
    ```bash
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    The application will be available at `http://localhost:8000`.
    Basic auth protects the dashboard, API, static assets, and health endpoint.

## Creating a Custom Provider

Mirrarr supports custom providers for fetching DDL links. Follow these steps to add a new provider.

### 1. Create the Provider File

Create a new file in `app/providers/`, e.g., `app/providers/my_custom_provider.py`.

Inherit from `ProviderInterface` and implement the required methods:

```python
from typing import List, Any
from app.providers.base import ProviderInterface, MovieResult, EpisodeResult
from app.models.media import Movie, TVSeries

class MyCustomProvider(ProviderInterface):
    @property
    def name(self) -> str:
        """Unique name of the provider."""
        return "MyCustomProvider"

    async def get_movie(self, movie: Movie) -> List[MovieResult]:
        """Search for movie download links."""
        # Implement your scraping/API logic here
        return [
            MovieResult(
                title=movie.title,
                quality="1080p",
                size=1073741824,  # Size in bytes
                download_url="https://example.com/download/movie.mkv",
                source_site=self.name,
                filename=f"{movie.title}.1080p.mkv"
            )
        ]

    async def get_series_episode(
        self,
        series: TVSeries,
        season: int,
        episode: int,
    ) -> List[EpisodeResult]:
        """Search for episode download links."""
        # Implement your scraping/API logic here
        return [
            EpisodeResult(
                title=f"{series.title} S{season}E{episode}",
                quality="1080p",
                size=524288000,  # Size in bytes
                download_url="https://example.com/download/episode.mkv",
                source_site=self.name,
                filename=f"{series.title}.S{season}E{episode}.1080p.mkv",
                season=season,
                episode=episode
            )
        ]

    def get_yt_opts(self) -> dict[str, Any]:
        """Optional: Custom yt-dlp options (headers, cookies, etc.)."""
        return {
            "http_headers": {
                "User-Agent": "MyCustomAgent/1.0",
                "Referer": "https://example.com/"
            }
        }
```

### 2. Register the Provider

Open `app/main.py` and register your new provider instance:

```python
from app.providers import register_provider
# ... other imports ...
from app.providers.my_custom_provider import MyCustomProvider  # Import your class

# ... existing registrations ...
register_provider(MyCustomProvider())
```

### 3. Restart the Application

Restart Mirrarr. Your new provider will now be queried when searching for content.

## Contributing

We welcome contributions! If you've created a custom provider that you think would be useful to others, please feel free to open a Pull Request.

1.  **Fork the repository**.
2.  **Create your feature branch** (`git checkout -b feature/AmazingProvider`).
3.  **Commit your changes** (`git commit -m 'Add AmazingProvider'`).
4.  **Push to the branch** (`git push origin feature/AmazingProvider`).
5.  **Open a Pull Request**.

Please ensure your provider follows the `ProviderInterface` and includes appropriate error handling. Using `uvx ruff check .` and `uvx ruff format .` is highly recommended before submitting.
