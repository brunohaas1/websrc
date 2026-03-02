"""
Plugin System for WebSRC Dashboard.

Plugins are auto-discovered from the ``app/plugins/`` directory.
Each plugin module must expose a ``register(registry)`` function
that receives a :class:`PluginRegistry` and registers hooks.

Supported hooks
---------------
- **collector**  – A callable ``(app, repo) -> int`` invoked on each
  frequent-jobs cycle.  Return the number of items inserted.
- **daily_job**  – A callable ``(app, repo) -> None`` invoked once a day.
- **route**      – A Flask blueprint to be registered on the app.
- **template_card** – An HTML snippet (str) appended to the dashboard grid.

Example plugin (``app/plugins/my_plugin.py``)::

    from app.plugins import PluginRegistry

    def my_collector(app, repo):
        # fetch + store items …
        return 0

    def register(registry: PluginRegistry):
        registry.add_collector("my_plugin", my_collector)
"""

from __future__ import annotations

import importlib
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PluginRegistry:
    """Central store for all registered plugin hooks."""

    collectors: dict[str, Callable] = field(default_factory=dict)
    daily_jobs: dict[str, Callable] = field(default_factory=dict)
    blueprints: list[Any] = field(default_factory=list)
    template_cards: list[str] = field(default_factory=list)

    # ── registration helpers ──────────────────────────────

    def add_collector(self, name: str, fn: Callable) -> None:
        self.collectors[name] = fn
        logger.info("Plugin collector registered: %s", name)

    def add_daily_job(self, name: str, fn: Callable) -> None:
        self.daily_jobs[name] = fn
        logger.info("Plugin daily job registered: %s", name)

    def add_blueprint(self, bp: Any) -> None:
        self.blueprints.append(bp)
        logger.info("Plugin blueprint registered: %s", getattr(bp, "name", bp))

    def add_template_card(self, html: str) -> None:
        self.template_cards.append(html)

    # ── execution helpers ─────────────────────────────────

    def run_collectors(self, app: Any, repo: Any) -> dict[str, int]:
        results: dict[str, int] = {}
        for name, fn in self.collectors.items():
            try:
                results[name] = fn(app, repo)
            except Exception:
                logger.exception("Plugin collector '%s' failed", name)
                results[name] = -1
        return results

    def run_daily_jobs(self, app: Any, repo: Any) -> None:
        for name, fn in self.daily_jobs.items():
            try:
                fn(app, repo)
            except Exception:
                logger.exception("Plugin daily job '%s' failed", name)


# ── singleton ────────────────────────────────────────────

_registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    """Return the global plugin registry."""
    return _registry


def discover_plugins() -> PluginRegistry:
    """Scan ``app/plugins/`` for modules with a ``register()`` function."""
    plugins_dir = pathlib.Path(__file__).parent
    for path in sorted(plugins_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"app.plugins.{path.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "register"):
                mod.register(_registry)
                logger.info("Plugin loaded: %s", module_name)
            else:
                logger.debug("Skipping %s (no register())", module_name)
        except Exception:
            logger.exception("Failed to load plugin %s", module_name)
    return _registry
