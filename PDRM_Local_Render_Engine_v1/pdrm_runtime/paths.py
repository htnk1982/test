from __future__ import annotations

from pathlib import Path
import os

APP_NAME = "PDRM_Local_Render_Engine_v1"


def default_state_base() -> Path:
    """Return a durable *local* state directory.

    The install tree may live on a mapped/network/removable drive. SQLite WAL
    and crash-recovery metadata should not depend on that volume. Users can
    override the location with PDRM_STATE_ROOT when they intentionally need a
    different local fixed-volume path.
    """
    override = os.environ.get("PDRM_STATE_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
        if base:
            return (Path(base) / APP_NAME).resolve()

    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return (Path(xdg).expanduser() / APP_NAME).resolve()

    return (Path.home() / ".local" / "state" / APP_NAME).resolve()


def default_runtime_root() -> Path:
    return default_state_base() / "runtime"


def default_acceptance_root() -> Path:
    return default_state_base() / "acceptance"
