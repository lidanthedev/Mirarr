from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.plugins.loader import get_plugin_overview, load_plugins, set_plugin_enabled, set_plugin_order
from app.providers import ProviderRegistry


@pytest.fixture(autouse=True)
def no_bundled_seeding(monkeypatch: pytest.MonkeyPatch):
    """Prevent bundled plugins from being seeded into test directories."""
    monkeypatch.setattr("app.plugins.loader._bundled_plugins_root", lambda: Path("/nonexistent"))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TMDB_API_KEY", "dummy")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _write_plugin(plugin_dir: Path, class_name: str, provider_name: str, *, broken: bool = False) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if broken:
        source = "raise RuntimeError('boom')\n"
    else:
        source = "\n".join([
            "from app.plugins.base import PluginInterface",
            "",
            f"class {class_name}(PluginInterface):",
            "    def __init__(self):",
            "        pass",
            "",
            "    @property",
            "    def name(self):",
            f'        return "{provider_name}"',
            "",
            "    async def get_movie(self, movie):",
            "        return []",
            "",
            "    async def get_series_episode(self, series, season, episode):",
            "        return []",
            "",
            "    def get_yt_opts(self):",
            "        return {}",
            "",
        ])
    (plugin_dir / "plugin.py").write_text(source)


def test_plugins_page_renders(client):
    response = client.get("/plugins")
    assert response.status_code == 200
    assert "Plugins" in response.text


def test_plugin_enable_disable_and_order(tmp_path: Path):
    data_dir = tmp_path / "data"
    plugins_root = data_dir / "plugins"
    _write_plugin(plugins_root / "alpha", "AlphaPlugin", "Alpha")
    _write_plugin(plugins_root / "beta", "BetaPlugin", "Beta")

    loaded = load_plugins(data_dir)
    assert loaded == ["Alpha", "Beta"]
    assert ProviderRegistry.names() == ["Alpha", "Beta"]

    set_plugin_enabled(data_dir, "alpha", False)
    overview = get_plugin_overview(data_dir)
    alpha = next(item for item in overview if item["plugin_id"] == "alpha")
    assert alpha["status"] == "disabled"
    assert ProviderRegistry.names() == ["Beta"]

    set_plugin_order(data_dir, ["beta", "alpha"])
    overview = get_plugin_overview(data_dir)
    assert [item["plugin_id"] for item in overview] == ["beta", "alpha"]
    assert overview[0]["status"] == "loaded"
    assert overview[1]["status"] == "disabled"


def test_failed_plugin_load_shows_error_state(tmp_path: Path):
    data_dir = tmp_path / "data"
    plugins_root = data_dir / "plugins"
    _write_plugin(plugins_root / "bad_plugin", "BadPlugin", "Bad", broken=True)

    loaded = load_plugins(data_dir)
    assert loaded == []

    overview = get_plugin_overview(data_dir)
    bad = next(item for item in overview if item["plugin_id"] == "bad_plugin")
    assert bad["status"] == "error"
    assert bad["error_message"]
