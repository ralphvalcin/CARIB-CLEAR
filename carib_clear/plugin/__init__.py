"""CARIB-CLEAR Plugin System — decorator-based plugin registration + discovery."""

from .registry import PluginSpec, PluginRegistry, plugin_registry

__all__ = ["PluginSpec", "PluginRegistry", "plugin_registry"]
