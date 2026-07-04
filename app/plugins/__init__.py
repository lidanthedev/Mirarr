
"""Plugin discovery and plugin interfaces."""

from app.plugins.base import PluginConfig, PluginInterface
from app.plugins.loader import (
    get_plugin_manifest,
    get_plugin_overview,
    load_plugins,
    reload_plugins,
    seed_bundled_plugins,
    set_plugin_enabled,
    set_plugin_order,
)

__all__ = [
    "PluginConfig",
    "PluginInterface",
    "get_plugin_manifest",
    "get_plugin_overview",
    "load_plugins",
    "reload_plugins",
    "seed_bundled_plugins",
    "set_plugin_enabled",
    "set_plugin_order",
]
