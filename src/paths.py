"""Filesystem layout for the application.

Runtime data is deliberately kept *outside* the repository so that login
cookies and captured order data can never be committed by accident.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "supplier-portal-automation"


def app_data_dir() -> Path:
    """Per-user writable directory for profiles, state and run artifacts.

    ``SUPPLIER_AUTOMATION_HOME`` overrides the location, which keeps demos and
    tests away from a real profile directory and its login cookies.
    """
    override = os.environ.get("SUPPLIER_AUTOMATION_HOME")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def browser_profile_dir() -> Path:
    """Persistent Chromium profile.

    Keeping one long-lived profile is what makes the portal treat this machine
    as an already-verified device, so SMS verification is only needed once.
    """
    return app_data_dir() / "browser-profile"


def state_dir() -> Path:
    return app_data_dir() / "state"


def runs_dir() -> Path:
    return app_data_dir() / "runs"


def config_dir() -> Path:
    return app_data_dir() / "config"


def ensure_dirs() -> None:
    for path in (browser_profile_dir(), state_dir(), runs_dir(), config_dir()):
        path.mkdir(parents=True, exist_ok=True)
