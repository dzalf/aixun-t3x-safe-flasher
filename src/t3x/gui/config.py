# SPDX-License-Identifier: GPL-2.0-or-later
"""GUI preferences kept in ONE file inside the workspace (aixun/config/gui.json).

Nothing is written to ~/.config: `./aixun gui` passes the file path in T3X_CONFIG,
and Qt's own settings (e.g. the file dialog's history) are redirected to the same
folder (see app.py). Without T3X_CONFIG nothing is remembered.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from typing import List, Optional

ENV = "T3X_CONFIG"


@dataclass
class GuiConfig:
    firmware_dir: Optional[str] = None       # last folder chosen with "Folder…"
    geometry: List[int] = field(default_factory=list)   # x, y, width, height
    cross_check: bool = True                 # Check online: compare with the second address
    update_notice: bool = False              # after a probe, look for a newer version online (opt-in)
    path: Optional[str] = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, path: Optional[str]) -> "GuiConfig":
        cfg = cls(path=path)
        if not path:
            return cfg
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cfg                       # missing or unreadable: defaults, never fatal
        if isinstance(data, dict):
            names = {f.name for f in fields(cls)} - {"path"}
            for k, v in data.items():
                if k in names:
                    setattr(cfg, k, v)
        if not (isinstance(cfg.geometry, list) and len(cfg.geometry) == 4
                and all(isinstance(x, int) for x in cfg.geometry)):
            cfg.geometry = []
        return cfg

    def save(self) -> bool:
        if not self.path:
            return False
        data = {k: v for k, v in asdict(self).items() if k != "path"}
        d = os.path.dirname(self.path) or "."
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".gui-")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False


def default_path() -> Optional[str]:
    return os.environ.get(ENV) or None
