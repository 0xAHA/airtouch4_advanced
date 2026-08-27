"""Shared test fixtures.

The integration package's __init__.py imports coordinator.py, which in turn
imports homeassistant and airtouch4pyapi - neither of which these tests need
to install just to exercise listener.py's pure-asyncio echo/refresh logic.
Loading listener.py directly by file path (rather than via the
custom_components.airtouch4_advanced package) sidesteps that whole
dependency chain and keeps these tests fast and dependency-light.
"""

import importlib.util
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LISTENER_PATH = _REPO_ROOT / "custom_components" / "airtouch4_advanced" / "listener.py"


def _load_listener_module():
    spec = importlib.util.spec_from_file_location(
        "airtouch4_advanced_listener_under_test", _LISTENER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


listener_module = _load_listener_module()
