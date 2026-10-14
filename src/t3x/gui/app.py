# SPDX-License-Identifier: GPL-2.0-or-later
"""t3x-gui entry point.

    t3x-gui                               # real station
    t3x-gui --sim                         # built-in simulated T3BS 1.06 (no iron needed)
    t3x-gui --sim --sim-fail-at-chunk 31  # simulate a cable pull, then try recovery
"""

from __future__ import annotations

import argparse
import os
import sys


def _default_dir(env: str, name: str) -> str:
    if os.environ.get(env):
        return os.environ[env]
    cand = os.path.join(os.getcwd(), name)
    return cand if os.path.isdir(cand) else os.getcwd()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="T3x Safe Updater GUI")
    ap.add_argument("--firmware-dir", default=None, help="folder with .bin images (default: ./firmware)")
    ap.add_argument("--results-dir", default=None, help="folder for flash logs and reports (default: ./results)")
    ap.add_argument("--wait", type=float, default=20, help="seconds to wait for re-enumeration")
    ap.add_argument("--no-auto-probe", action="store_true", help="don't probe automatically when a station appears")
    ap.add_argument("--config", default=None,
                    help="preferences file (default: $T3X_CONFIG; './aixun gui' uses <workspace>/config/gui.json). "
                         "Without one, nothing is remembered")
    g = ap.add_argument_group("simulator (no hardware)")
    g.add_argument("--sim", action="store_true", help="use a built-in simulated station")
    g.add_argument("--sim-product", default="T3BS")
    g.add_argument("--sim-version", default="1.06")
    g.add_argument("--sim-bootloader", action="store_true", help="start in bootloader (recovery) mode")
    g.add_argument("--sim-fail-at-chunk", type=int, help="drop off USB at this chunk (first transfer only, "
                                                          "like a real cable pull)")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QStyleFactory
    except ImportError:
        sys.exit("PySide6 is not installed in this environment: pip install -e \".[gui]\" "
                 "(or './aixun setup' in the workspace)")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("QT_QPA_PLATFORM")):
        sys.exit("No desktop session found (DISPLAY and WAYLAND_DISPLAY are empty). Start t3x-gui from a "
                 "terminal inside the desktop, not over SSH.")
    from PySide6.QtCore import QSettings
    from ..core.link import SerialLink
    from . import theme
    from .config import GuiConfig, default_path
    from .window import MainWindow, Settings

    cfg = GuiConfig.load(a.config or default_path())
    if cfg.path:
        # Qt keeps its own small settings (e.g. the file dialog's history) in ~/.config/QtProject.conf.
        # Point them at the workspace's config folder instead, so nothing lands outside it.
        cfg_dir = os.path.dirname(os.path.abspath(cfg.path))
        os.makedirs(cfg_dir, exist_ok=True)
        for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
            QSettings.setPath(fmt, QSettings.UserScope, cfg_dir)
    fw_dir = a.firmware_dir or (cfg.firmware_dir if cfg.firmware_dir and os.path.isdir(cfg.firmware_dir) else None) \
        or _default_dir("T3X_FIRMWARE_DIR", "firmware")
    s = Settings(firmware_dir=fw_dir,
                 results_dir=a.results_dir or _default_dir("T3X_RESULTS_DIR", "results"),
                 wait=a.wait, auto_probe=not a.no_auto_probe, config=cfg)
    sim = None
    if a.sim:
        s.results_dir = os.path.join(s.results_dir, "sim")      # never mixed with real logs and history
        s.simulated = True
        from ..sim.station import Scenario, SimStation
        sc = Scenario(product=a.sim_product.encode(), app_version=a.sim_version.encode(),
                      bootloader_string=b"00160000JC_M_" + a.sim_product.encode() + b"_version1.01",
                      start_in_bootloader=a.sim_bootloader, fail_at_chunk=a.sim_fail_at_chunk,
                      reenum_delay=0.6)
        sim = SimStation(sc)
        sim.start()
        s.port_lister = sim.port_lister
        s.link_factory = lambda emit: SerialLink(None, a.wait, emit=emit, port_lister=sim.port_lister)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle(QStyleFactory.create("Fusion"))
    f = QFont("Inter")
    f.setPointSize(10)
    app.setFont(f)
    app.setStyleSheet(theme.QSS)
    w = MainWindow(s)
    if sim:
        w.setWindowTitle("T3x Safe Updater  [SIMULATED STATION]")
    w.show()
    try:
        return app.exec()
    finally:
        if sim:
            sim.stop()


if __name__ == "__main__":
    sys.exit(main())
