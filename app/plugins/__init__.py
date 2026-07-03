
"""Plugin discovery and plugin interfaces."""

from app.plugins.base import PluginConfig, PluginInterface
from app.plugins.loader import load_plugins, seed_bundled_plugins

__all__ = ["PluginConfig", "PluginInterface", "load_plugins", "seed_bundled_plugins"]
