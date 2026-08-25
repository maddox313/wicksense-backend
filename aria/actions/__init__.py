"""Load all action modules — each module self-registers on import.

To add a new WickSense capability:
  1. Create e.g. aria/actions/my_feature_actions.py
  2. Call registry.register_action(name, description, handler, category=..., ...)
  3. Import the module below in load_all_actions()

No changes to dispatcher.py, chat.py, or routes.py are required.
"""

from __future__ import annotations

_loaded = False


def load_all_actions() -> None:
    global _loaded
    if _loaded:
        return
    # Import order does not matter — registry prevents duplicates
    from aria.actions import (  # noqa: F401
        integration_actions,
        navigation_actions,
        platform_actions,
        strategy_actions,
        trading_actions,
    )
    # Truth gateway registers JWT-bound read tools
    import aria.truth_gateway  # noqa: F401
    _loaded = True
