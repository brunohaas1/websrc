"""
Example plugin – demonstrates the plugin interface.

Drop any ``.py`` file in ``app/plugins/`` and expose a ``register(registry)``
function to extend the dashboard with custom collectors, daily jobs,
blueprints, or template cards.

This file is intentionally a no-op; rename / edit to taste.
"""

from __future__ import annotations

from app.plugins import PluginRegistry


def _example_collector(app, repo) -> int:  # noqa: ARG001
    """Return 0 – does nothing.  Replace with real logic."""
    return 0


def register(registry: PluginRegistry) -> None:
    # Uncomment the line below to activate:
    # registry.add_collector("example", _example_collector)
    pass
