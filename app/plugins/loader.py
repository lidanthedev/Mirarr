"""Filesystem plugin discovery, seeding, and runtime reload."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import re
import shutil
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.config import get_settings
from app.plugins.base import PluginConfig, PluginInterface
from app.plugins.state import (
    PluginManifest,
    PluginStateEntry,
    build_plugin_entry_map,
    get_plugins_root,
    load_manifest,
    save_manifest,
    sync_manifest_with_files,
)
from app.providers import ProviderRegistry

logger = logging.getLogger(__name__)


def _sanitize_module_name(name: str) -> str:
    return re.sub(r"\W+", "_", name).strip("_") or "plugin"


def _bundled_plugins_root() -> Path:
    return Path(__file__).resolve().parent / "bundled"


def seed_bundled_plugins(plugins_root: Path) -> bool:
    """Copy bundled plugins into the data folder on first run."""
    if plugins_root.exists():
        return False

    bundled_root = _bundled_plugins_root()
    if not bundled_root.exists():
        logger.warning("Bundled plugin directory not found at %s", bundled_root)
        return False

    try:
        plugins_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled_root, plugins_root)
        logger.info("Seeded bundled plugins into %s", plugins_root)
        return True
    except Exception:
        logger.exception("Failed to seed bundled plugins into %s", plugins_root)
        return False


def _load_module_from_path(module_name: str, module_path: Path) -> object:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load plugin module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    plugin_dir = str(module_path.parent)
    sys.path.insert(0, plugin_dir)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(plugin_dir)
        except ValueError:
            pass
    return module


def _find_plugin_class(module: object) -> type[PluginInterface] | None:
    candidates: list[type[PluginInterface]] = []
    for value in module.__dict__.values():
        if not inspect.isclass(value):
            continue
        if value is PluginInterface or value is PluginConfig:
            continue
        if not issubclass(value, PluginInterface):
            continue
        if inspect.isabstract(value):
            continue
        if value.__module__ != module.__name__:
            continue
        candidates.append(value)

    if not candidates:
        logger.warning("No concrete PluginInterface subclass found in %s", module.__name__)
        return None

    if len(candidates) > 1:
        names = ", ".join(candidate.__name__ for candidate in candidates)
        logger.warning(
            "Multiple PluginInterface subclasses found in %s (%s); skipping",
            module.__name__,
            names,
        )
        return None

    return candidates[0]


def _load_plugin_config(plugin_dir: Path, plugin_cls: type[PluginInterface]) -> PluginConfig | None:
    config_model = getattr(plugin_cls, "config_model", None)
    if config_model is None:
        return None

    if not inspect.isclass(config_model) or not issubclass(config_model, PluginConfig):
        raise TypeError(f"{plugin_cls.__name__}.config_model must inherit from PluginConfig")

    config_path = plugin_dir / "config.json"
    try:
        if config_path.exists():
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))
            return config_model.model_validate(raw_config)

        config = config_model()
        config_path.write_text(
            json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return config
    except (OSError, TypeError, ValueError, ValidationError):
        logger.exception(
            "Failed to load or write config for plugin %s in %s",
            plugin_cls.__name__,
            plugin_dir,
        )
        return None


def _close_provider_best_effort(provider: PluginInterface) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(close())
        return

    running_loop.create_task(close())


def _close_all_providers() -> None:
    for provider in ProviderRegistry.all():
        _close_provider_best_effort(provider)


def get_plugin_manifest(data_dir: Path | None = None) -> PluginManifest:
    """Return the current plugin manifest, seeded and synced with files."""
    plugins_root = get_plugins_root(data_dir)
    seed_bundled_plugins(plugins_root)
    plugins_root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(plugins_root)
    manifest, changed = sync_manifest_with_files(plugins_root, manifest)
    if changed:
        save_manifest(plugins_root, manifest)
    return manifest


def get_plugin_overview(data_dir: Path | None = None) -> list[dict[str, object]]:
    """Return plugin metadata for the plugins page."""
    plugins_root = get_plugins_root(data_dir)
    manifest = get_plugin_manifest(data_dir)
    entry_map = build_plugin_entry_map(manifest)

    overview: list[dict[str, object]] = []
    if plugins_root.exists():
        for plugin_dir in sorted(path for path in plugins_root.iterdir() if path.is_dir()):
            plugin_id = plugin_dir.name
            state = entry_map.get(plugin_id)
            overview.append(
                {
                    "plugin_id": plugin_id,
                    "title": state.title if state and state.title else plugin_id,
                    "enabled": state.enabled if state else True,
                    "order": state.order if state else 0,
                    "exists": True,
                    "config_exists": (plugin_dir / "config.json").exists(),
                    "path": str(plugin_dir),
                }
            )

    known_dirs = {row["plugin_id"] for row in overview}
    for state in sorted(manifest.plugins, key=lambda entry: (entry.order, entry.plugin_id)):
        if state.plugin_id in known_dirs:
            continue
        overview.append(
            {
                "plugin_id": state.plugin_id,
                "title": state.title or state.plugin_id,
                "enabled": state.enabled,
                "order": state.order,
                "exists": False,
                "config_exists": False,
                "path": str(plugins_root / state.plugin_id),
            }
        )

    overview.sort(key=lambda row: (int(row["order"]), str(row["plugin_id"])))
    return overview


def reload_plugins(data_dir: Path | None = None) -> list[str]:
    """Close loaded providers, clear the registry, and load plugins again."""
    _close_all_providers()
    ProviderRegistry.clear()
    return load_plugins(data_dir)


def load_plugins(data_dir: Path | None = None) -> list[str]:
    """Load plugins from the data/plugins directory."""
    settings = get_settings()
    if data_dir is None:
        data_dir = Path(settings.data_dir)
    plugins_root = get_plugins_root(data_dir)
    seed_bundled_plugins(plugins_root)
    plugins_root.mkdir(parents=True, exist_ok=True)

    if not plugins_root.exists():
        logger.info("Plugin directory does not exist: %s", plugins_root)
        return []

    manifest = load_manifest(plugins_root)
    manifest, changed = sync_manifest_with_files(plugins_root, manifest)
    if changed:
        save_manifest(plugins_root, manifest)

    entry_map = build_plugin_entry_map(manifest)
    loaded_plugins: list[str] = []

    for plugin_dir in sorted(path for path in plugins_root.iterdir() if path.is_dir()):
        plugin_id = plugin_dir.name
        state = entry_map.get(plugin_id)
        if state is None:
            continue
        if not state.enabled:
            logger.info("Skipping disabled plugin %s", plugin_id)
            continue

        plugin_file = plugin_dir / "plugin.py"
        if not plugin_file.exists():
            logger.warning("Skipping %s: missing plugin.py", plugin_dir)
            continue

        module_name = f"mirrarr_plugins.{_sanitize_module_name(plugin_id)}.plugin"
        try:
            module = _load_module_from_path(module_name, plugin_file)
            plugin_cls = _find_plugin_class(module)
            if plugin_cls is None:
                continue

            config = _load_plugin_config(plugin_dir, plugin_cls)
            if plugin_cls.config_model is not None and config is None:
                continue

            provider = plugin_cls()
            if config is not None:
                provider.config = config

            if ProviderRegistry.get(provider.name) is not None:
                logger.warning(
                    "Skipping plugin %s from %s: provider name already registered",
                    provider.name,
                    plugin_dir,
                )
                _close_provider_best_effort(provider)
                continue

            ProviderRegistry.register(provider)
            state.title = provider.name
            loaded_plugins.append(provider.name)
            logger.info("Loaded plugin %s from %s", provider.name, plugin_dir)
        except Exception:
            logger.exception("Failed to load plugin from %s", plugin_dir)

    save_manifest(plugins_root, manifest)
    return loaded_plugins


def set_plugin_enabled(data_dir: Path | None, plugin_id: str, enabled: bool) -> list[str]:
    plugins_root = get_plugins_root(data_dir)
    manifest = get_plugin_manifest(data_dir)
    updated = False
    for entry in manifest.plugins:
        if entry.plugin_id == plugin_id:
            entry.enabled = enabled
            updated = True
            break
    if updated:
        save_manifest(plugins_root, manifest)
    return reload_plugins(data_dir)


def set_plugin_order(data_dir: Path | None, ordered_ids: list[str]) -> list[str]:
    plugins_root = get_plugins_root(data_dir)
    manifest = get_plugin_manifest(data_dir)
    lookup = build_plugin_entry_map(manifest)
    new_plugins: list[PluginStateEntry] = []

    for index, plugin_id in enumerate(ordered_ids):
        entry = lookup.get(plugin_id)
        if entry is None:
            continue
        entry.order = index
        new_plugins.append(entry)

    remaining = [entry for entry in manifest.plugins if entry.plugin_id not in ordered_ids]
    for offset, entry in enumerate(sorted(remaining, key=lambda e: (e.order, e.plugin_id)), start=len(new_plugins)):
        entry.order = offset
        new_plugins.append(entry)

    manifest.plugins = new_plugins
    save_manifest(plugins_root, manifest)
    return reload_plugins(data_dir)
