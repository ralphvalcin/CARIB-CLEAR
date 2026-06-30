"""CARIB-CLEAR Plugin System — Decorator-based plugin registration + discovery.

Plugins auto-register themselves with metadata using the @PluginSpec.register()
decorator. The PluginRegistry discovers them at startup so the system can
load new rails, lenders, currencies, and agents without code changes.

Usage:
    from carib_clear.plugin import PluginSpec, PluginRegistry

    @PluginSpec.register("stellar_usdc", {
        "type": "settlement_rail",
        "currencies": ["BBD", "JMD", ...],
        ...
    })
    class StellarAdapter(MultiRailBroker):
        ...

    # Later, at startup:
    registry = PluginRegistry()
    registry.discover()
    rails = registry.get_plugins("settlement_rail")
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class PluginSpec:
    """Descriptor for a registered plugin with metadata and class reference."""

    __plugin_registry__: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, plugin_id: str, metadata: dict):
        """Decorator that registers a class as a plugin.

        Stores the module path for reliable re-import (avoids class identity
        issues from circular imports).

        Args:
            plugin_id: Unique identifier (e.g. 'stellar_usdc', 'barita_lender')
            metadata: Dict with at minimum {"type": "settlement_rail"|"lender"|"agent"}

        Returns:
            Decorator that registers the class and returns it unchanged.
        """
        def decorator(klass):
            cls.__plugin_registry__[plugin_id] = {
                "id": plugin_id,
                "module": klass.__module__,
                "class_name": klass.__qualname__,
                "class": klass,
                "metadata": metadata,
                "enabled": metadata.get("enabled", True),
            }
            logger.debug("[Plugin] Registered %s (%s from %s)", plugin_id, metadata.get("type", "unknown"), klass.__module__)
            return klass
        return decorator

    @classmethod
    def get(cls, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Get a registered plugin by ID."""
        return cls.__plugin_registry__.get(plugin_id)

    @classmethod
    def all(cls) -> Dict[str, Dict[str, Any]]:
        """Return all registered plugins."""
        return dict(cls.__plugin_registry__)


class PluginRegistry:
    """Discovers and serves registered plugins.

    Handles:
      - Auto-discovery via Python entry_points or package scanning
      - Querying plugins by type, capability, or ID
      - Enabling/disabling plugins at runtime
    """

    def __init__(self):
        self._plugins: Dict[str, Dict[str, Any]] = {}

    def discover(self, package: str = "carib_clear.plugins") -> int:
        """Auto-discover plugins via entry_points or package scanning.

        Two strategies:
          1. Python entry_points (pyproject.toml [project.entry-points])
          2. Scanning the plugins namespace package

        Returns:
            Number of plugins discovered.
        """
        count = 0

        # Strategy 1: Python entry_points (preferred for pip-installed plugins)
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="carib_clear.plugins")
            for ep in eps:
                try:
                    cls = ep.load()
                    # The class decorator already registered it
                    logger.info("[Plugin] Discovered via entry_point: %s", ep.name)
                    count += 1
                except Exception as e:
                    logger.warning("[Plugin] Failed to load entry_point %s: %s", ep.name, e)
        except Exception:
            pass

        # Strategy 2: Scan package namespace for decorated classes
        try:
            mod = importlib.import_module(package)
            for importer, modname, ispkg in pkgutil.iter_modules(
                mod.__path__, prefix=f"{package}."
            ):
                try:
                    importlib.import_module(modname)
                    logger.debug("[Plugin] Scanned module: %s", modname)
                except Exception as e:
                    logger.warning("[Plugin] Failed to scan %s: %s", modname, e)
        except ImportError:
            pass

        # Merge into internal dict
        self._plugins.update(PluginSpec.all())
        count += len(PluginSpec.all())

        logger.info("[Plugin] Registry: %d plugins (%d newly discovered)",
                     len(self._plugins), count)
        return count

    def register(self, plugin_id: str, metadata: dict, klass: Type) -> None:
        """Directly register a plugin (without decorator).

        Useful for plugins created at runtime or from config files.
        """
        self._plugins[plugin_id] = {
            "id": plugin_id,
            "class": klass,
            "metadata": metadata,
            "enabled": metadata.get("enabled", True),
        }
        logger.debug("[Plugin] Directly registered %s", plugin_id)

    def get(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Get a plugin by ID."""
        return self._plugins.get(plugin_id)

    def get_plugins(self, plugin_type: str) -> List[Dict[str, Any]]:
        """Get all plugins of a given type.

        Args:
            plugin_type: 'settlement_rail', 'lender', 'agent', etc.

        Returns:
            List of matching plugin dicts (enabled only).
        """
        return [
            p for p in self._plugins.values()
            if p["metadata"].get("type") == plugin_type and p["enabled"]
        ]

    def get_rails_for_pair(self, from_ccy: str, to_ccy: str) -> List[Dict[str, Any]]:
        """Get settlement rails that support a given currency pair."""
        return [
            p for p in self.get_plugins("settlement_rail")
            if from_ccy in p["metadata"].get("currencies", [])
            and to_ccy in p["metadata"].get("currencies", [])
        ]

    def get_rails_for_jurisdiction(self, jurisdiction: str) -> List[Dict[str, Any]]:
        """Get settlement rails that support a given jurisdiction."""
        return [
            p for p in self.get_plugins("settlement_rail")
            if jurisdiction in p["metadata"].get("jurisdictions", [])
        ]

    def get_lenders_for_jurisdiction(self, jurisdiction: str) -> List[Dict[str, Any]]:
        """Get lenders that operate in a given jurisdiction."""
        return [
            p for p in self.get_plugins("lender")
            if jurisdiction in p["metadata"].get("jurisdictions", [])
        ]

    def enable(self, plugin_id: str) -> bool:
        """Enable a plugin."""
        if plugin_id in self._plugins:
            self._plugins[plugin_id]["enabled"] = True
            PluginSpec.__plugin_registry__[plugin_id]["enabled"] = True
            return True
        return False

    def disable(self, plugin_id: str) -> bool:
        """Disable a plugin."""
        if plugin_id in self._plugins:
            self._plugins[plugin_id]["enabled"] = False
            PluginSpec.__plugin_registry__[plugin_id]["enabled"] = False
            return True
        return False

    def instantiate(self, plugin_id: str, **kwargs) -> Any:
        """Create an instance of a plugin class.

        Re-imports the class from its module to avoid stale class references
        from circular import chains.

        Args:
            plugin_id: The plugin ID to instantiate.
            **kwargs: Passed to the plugin's __init__.

        Returns:
            An instance of the plugin class, or None if not found.
        """
        plugin = self.get(plugin_id)
        if not plugin or not plugin["enabled"]:
            return None
        try:
            # Re-import the class fresh from its module to avoid stale ABC references
            import importlib
            mod = importlib.import_module(plugin["module"])
            klass = getattr(mod, plugin["class_name"])
            return klass(**kwargs)
        except Exception as e:
            logger.error("[Plugin] Failed to instantiate %s: %s", plugin_id, e)
            return None

    def list_plugins(self, plugin_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all plugins, optionally filtered by type."""
        if plugin_type:
            return self.get_plugins(plugin_type)
        return list(self._plugins.values())

    def reset(self) -> None:
        """Clear all registrations (useful for testing)."""
        self._plugins.clear()
        PluginSpec.__plugin_registry__.clear()


# ─── Convenience ──────────────────────────────────────────────────────

plugin_registry = PluginRegistry()
"""Global singleton registry instance."""
