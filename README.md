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

## Creating a Custom Plugin

Mirrarr supports filesystem plugins for fetching DDL links. Each plugin lives in its own folder under the data plugins directory and is loaded from `plugin.py` at startup.

### 1. Create the Plugin Folder

Create a new folder inside `<data_dir>/plugins/`, e.g., `data/plugins/my_custom_provider/`.

Implement `PluginInterface`, and add a `config_model` extending `PluginConfig` if your plugin needs configuration:

```python
from typing import List, Any
from app.plugins.base import PluginInterface, PluginConfig
from app.providers.base import MovieResult, EpisodeResult
from app.models.media import Movie, TVSeries

class MyConfig(PluginConfig):
    api_key: str = ""

class MyCustomProvider(PluginInterface):
    config_model = MyConfig

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

### 2. Let Mirrarr Load It

Drop `plugin.py` into the plugin folder and restart Mirrarr. The loader will import every `plugin.py`, validate that it implements `PluginInterface`, and register it automatically.

If your plugin defines a `config_model`, Mirrarr will read or create a `config.json` next to `plugin.py` and validate it with Pydantic.

### 3. Restart the Application

Restart Mirrarr. Your new plugin will now be queried when searching for content.

## Contributing

We welcome contributions! If you've created a custom provider that you think would be useful to others, please feel free to open a Pull Request.

1.  **Fork the repository**.
2.  **Create your feature branch** (`git checkout -b feature/AmazingProvider`).
3.  **Commit your changes** (`git commit -m 'Add AmazingProvider'`).
4.  **Push to the branch** (`git push origin feature/AmazingProvider`).
5.  **Open a Pull Request**.

Please ensure your plugin follows the `PluginInterface` and includes appropriate error handling. Using `uvx ruff check .` and `uvx ruff format .` is highly recommended before submitting.


## Plugin Configuration

Plugins can optionally define a `config_model` that extends `PluginConfig`. When present, Mirrarr stores the plugin config as `config.json` in the same folder as `plugin.py`. Missing files are created from model defaults on first load. The config file is always JSON so users can edit it manually.
