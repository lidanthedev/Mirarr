"""Persistent plugin state for enablement and ordering."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings

MANIFEST_FILENAME = ".mirrarr-plugins.json"


class PluginStateEntry(BaseModel):
    """Persisted state for a plugin folder."""

    model_config = ConfigDict(extra="ignore")

    plugin_id: str
    enabled: bool = True
    order: int = 0
    title: str | None = None


class PluginManifest(BaseModel):
    """Top-level on-disk manifest for plugin state."""

    model_config = ConfigDict(extra="ignore")

    plugins: list[PluginStateEntry] = Field(default_factory=list)


def get_plugins_root(data_dir: Path | None = None) -> Path:
    """Return the filesystem root for plugins."""
    if data_dir is None:
        data_dir = Path(get_settings().data_dir)
    return Path(data_dir) / "plugins"


def get_manifest_path(plugins_root: Path) -> Path:
    return plugins_root / MANIFEST_FILENAME


def load_manifest(plugins_root: Path) -> PluginManifest:
    path = get_manifest_path(plugins_root)
    if not path.exists():
        return PluginManifest()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PluginManifest.model_validate(data)
    except Exception:
        return PluginManifest()


def save_manifest(plugins_root: Path, manifest: PluginManifest) -> None:
    path = get_manifest_path(plugins_root)
    plugins_root.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _next_order(entries: list[PluginStateEntry]) -> int:
    if not entries:
        return 0
    return max(entry.order for entry in entries) + 1


def sync_manifest_with_files(plugins_root: Path, manifest: PluginManifest) -> tuple[PluginManifest, bool]:
    """Ensure every plugin folder has a manifest entry."""
    changed = False
    known = {entry.plugin_id for entry in manifest.plugins}
    for plugin_dir in sorted(path for path in plugins_root.iterdir() if path.is_dir()):
        plugin_id = plugin_dir.name
        if plugin_id in known:
            continue
        manifest.plugins.append(
            PluginStateEntry(
                plugin_id=plugin_id,
                enabled=True,
                order=_next_order(manifest.plugins),
                title=plugin_id,
            )
        )
        changed = True

    manifest.plugins.sort(key=lambda entry: (entry.order, entry.plugin_id))
    return manifest, changed


def build_plugin_entry_map(manifest: PluginManifest) -> dict[str, PluginStateEntry]:
    return {entry.plugin_id: entry for entry in manifest.plugins}
