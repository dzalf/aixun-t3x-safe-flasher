# SPDX-License-Identifier: GPL-2.0-or-later
"""Facts about the host that matter for a flash, gathered without changing anything."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

SIM_ENV = "T3X_SIM_PORTS"


def simulated() -> bool:
    """True when the front-ends are pointed at the simulator (t3x-sim + T3X_SIM_PORTS)."""
    return bool(os.environ.get(SIM_ENV))


def modemmanager_active() -> Optional[bool]:
    """True/False from `systemctl is-active ModemManager`; None if that can't be asked.

    ModemManager opens newly appearing serial ports to look for modems. The station
    re-appears on USB twice during an update (bootloader entry, restart afterwards).
    Read-only: this never starts or stops anything.
    """
    override = os.environ.get("T3X_ASSUME_MODEMMANAGER")      # tests / unusual systems
    if override is not None:
        return override == "1"
    if not shutil.which("systemctl"):
        return None
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", "ModemManager"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode == 0


MM_NOTE = ("ModemManager is running. It may open the station's port each time the station "
           "re-appears on USB during the update. Optional, before flashing: "
           "sudo systemctl stop ModemManager  (it returns at the next reboot, or with: "
           "sudo systemctl start ModemManager)")
