
"""Plugin base classes and interfaces."""

from abc import ABC
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from app.providers.base import ProviderInterface


class PluginConfig(BaseModel):
    """Base model for plugin configuration."""

    model_config = ConfigDict(extra="forbid")


class PluginInterface(ProviderInterface, ABC):
    """Base interface for filesystem-loaded plugins."""

    config_model: ClassVar[type[PluginConfig] | None] = None
    config: PluginConfig | None = None

    def get_yt_opts(self) -> dict[str, Any]:
        """Return custom yt-dlp options for this plugin."""
        return super().get_yt_opts()
