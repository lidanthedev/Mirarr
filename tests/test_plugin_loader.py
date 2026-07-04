
import json
from pathlib import Path
from textwrap import dedent as td
from typing import cast

import pytest

from app.plugins.base import PluginInterface
from app.plugins.loader import load_plugins, seed_bundled_plugins
from app.providers import ProviderRegistry


def _write_plugin(plugin_dir: Path, *, body: str) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(td(body))


@pytest.fixture(autouse=True)
def clear_registry():
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


@pytest.fixture(autouse=True)
def no_bundled_seeding(monkeypatch: pytest.MonkeyPatch):
    """Prevent bundled plugins from being seeded into test directories."""
    monkeypatch.setattr("app.plugins.loader._bundled_plugins_root", lambda: Path("/nonexistent"))


def test_seed_bundled_plugins_creates_copy(tmp_path: Path):
    plugins_root = tmp_path / "plugins"
    real_bundled = Path(__file__).resolve().parent.parent / "app" / "plugins" / "bundled"

    import app.plugins.loader as loader_mod
    loader_mod._bundled_plugins_root = lambda: real_bundled
    try:
        seeded = seed_bundled_plugins(plugins_root)
    finally:
        loader_mod._bundled_plugins_root = lambda: Path("/nonexistent")

    assert seeded is True
    assert (plugins_root / "a111477" / "plugin.py").exists()
    assert (plugins_root / "acermovies" / "plugin.py").exists()
    assert (plugins_root / "rivestream" / "plugin.py").exists()
    assert (plugins_root / "vadapav" / "plugin.py").exists()
    assert (plugins_root / "aiostreams" / "plugin.py").exists()


def test_load_plugins_with_default_config_creates_json(tmp_path: Path):
    data_dir = tmp_path / "data"
    plugins_root = data_dir / "plugins"
    _write_plugin(
        plugins_root / "demo_plugin",
        body="""
            from app.plugins.base import PluginConfig, PluginInterface

            class DemoConfig(PluginConfig):
                greeting: str = "hello"
                retries: int = 3

            class DemoPlugin(PluginInterface):
                config_model = DemoConfig

                @property
                def name(self) -> str:
                    return "DemoPlugin"

                async def get_movie(self, movie):
                    return []

                async def get_series_episode(self, series, season, episode):
                    return []
        """,
    )

    loaded = load_plugins(data_dir)

    assert loaded == ["DemoPlugin"]
    provider = ProviderRegistry.get("DemoPlugin")
    assert provider is not None
    plugin = cast(PluginInterface, provider)
    assert plugin.config is not None
    assert plugin.config.greeting == "hello"  # type: ignore[attr-defined]
    assert plugin.config.retries == 3  # type: ignore[attr-defined]

    config_path = plugins_root / "demo_plugin" / "config.json"
    assert config_path.exists()
    config_data = json.loads(config_path.read_text())
    assert config_data == {"greeting": "hello", "retries": 3}


def test_load_plugins_with_existing_config(tmp_path: Path):
    data_dir = tmp_path / "data"
    plugins_root = data_dir / "plugins"
    plugin_dir = plugins_root / "configured_plugin"
    _write_plugin(
        plugin_dir,
        body="""
            from app.plugins.base import PluginConfig, PluginInterface

            class DemoConfig(PluginConfig):
                greeting: str = "hello"
                retries: int = 3

            class DemoPlugin(PluginInterface):
                config_model = DemoConfig

                @property
                def name(self) -> str:
                    return "ConfiguredPlugin"

                async def get_movie(self, movie):
                    return []

                async def get_series_episode(self, series, season, episode):
                    return []
        """,
    )
    (plugin_dir / "config.json").write_text('{"greeting": "hola", "retries": 7}')

    loaded = load_plugins(data_dir)

    assert loaded == ["ConfiguredPlugin"]
    provider = ProviderRegistry.get("ConfiguredPlugin")
    assert provider is not None
    plugin = cast(PluginInterface, provider)
    assert plugin.config is not None
    assert plugin.config.greeting == "hola"  # type: ignore[attr-defined]
    assert plugin.config.retries == 7  # type: ignore[attr-defined]


def test_load_plugins_skips_invalid_config(tmp_path: Path):
    data_dir = tmp_path / "data"
    plugins_root = data_dir / "plugins"
    plugin_dir = plugins_root / "broken_plugin"
    _write_plugin(
        plugin_dir,
        body="""
            from app.plugins.base import PluginConfig, PluginInterface

            class DemoConfig(PluginConfig):
                greeting: str = "hello"
                retries: int = 3

            class DemoPlugin(PluginInterface):
                config_model = DemoConfig

                @property
                def name(self) -> str:
                    return "BrokenPlugin"

                async def get_movie(self, movie):
                    return []

                async def get_series_episode(self, series, season, episode):
                    return []
        """,
    )
    (plugin_dir / "config.json").write_text('{"greeting": 1, "retries": "nope"}')

    loaded = load_plugins(data_dir)

    assert loaded == []
    assert ProviderRegistry.get("BrokenPlugin") is None


def test_load_plugins_skips_invalid_plugin_shape(tmp_path: Path):
    data_dir = tmp_path / "data"
    plugins_root = data_dir / "plugins"
    plugin_dir = plugins_root / "invalid_shape"
    _write_plugin(
        plugin_dir,
        body="""
            class NotAPlugin:
                pass
        """,
    )

    loaded = load_plugins(data_dir)

    assert loaded == []
    assert ProviderRegistry.names() == []
