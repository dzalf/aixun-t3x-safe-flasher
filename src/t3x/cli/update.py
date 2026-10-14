# SPDX-License-Identifier: GPL-2.0-or-later
"""t3x-update: hardened updater (same wire bytes and output as t3xupdate_safe.py)."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from ..core import environment, history
from ..core import events as ev
from ..core import image as fwimage
from ..core.flasher import Flasher, Preflight
from ..core.link import SerialLink
from ..core.logfile import SIM_MARKER, LogSink, file_handler, latest_log, new_log_path, parse_log


def setup_logging(debug: bool, log_dir: str):
    logger = logging.getLogger("t3x")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    path = new_log_path(log_dir)
    logger.addHandler(file_handler(path))
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG if debug else logging.INFO)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)
    return logger, path


def make_confirm(assume_yes: bool, mm_active: bool = False):
    def confirm(pf: Preflight) -> bool:
        img, st = pf.image, pf.station
        print("\n  ---- Pre-flight ------------------------------------")
        what = "bootloader v" if pf.in_bootloader else "v"     # don't pass the bootloader off as firmware
        print(f"  Station : {(st.product or b'?').decode(errors='replace')} "
              f"{what}{(st.raw[-4:]).decode(errors='replace')} ({pf.identity.decode(errors='replace')})")
        if pf.in_bootloader:
            print("  Recovery: the station is waiting in its bootloader; this will complete the update.")
        elif pf.same_version:
            print("  Note    : the station already runs this version (re-flash).")
        elif (st.version and img.version
              and fwimage.version_key(img.version) < fwimage.version_key(st.version)):
            print(f"  DOWNGRADE {st.version.decode()} -> {img.version_str}: older firmware may read the newer "
                  "one's settings differently (unverified); check settings and temperature afterwards.")
        print(f"  File    : {img.product_str} v{img.version_str}  ({img.size} bytes, {img.n_chunks} chunks)")
        if mm_active:
            print(f"  Note    : {environment.MM_NOTE}")
        print("  Do not unplug USB or switch off the station until this script finishes.")
        if assume_yes:
            return True
        return input("  Type 'yes' to flash: ").strip().lower() == "yes"
    return confirm


class Console:
    """Prints progress the way the original script did."""

    def __init__(self, sink):
        self.sink = sink
        self.progress_shown = False

    def __call__(self, e):
        if isinstance(e, ev.LogEvent) and self.progress_shown and e.level >= ev.logging.WARNING:
            print()                       # never glue a warning/error onto the progress line
            self.progress_shown = False
        self.sink(e)
        if isinstance(e, ev.ProgressEvent):
            print(f"\r  {e.index}/{e.total} chunks ({e.percent}%)", end="", flush=True)
            self.progress_shown = True
        elif isinstance(e, ev.StageEvent) and e.stage in (ev.Stage.VERIFY, ev.Stage.FAILED) and self.progress_shown:
            print()
            self.progress_shown = False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hardened AiXun T3x updater")
    ap.add_argument("file", help="update .bin (JCID header)")
    ap.add_argument("-d", "--debug", action="store_true", help="show TX/RX on screen too")
    ap.add_argument("--port", help="explicit serial port, e.g. /dev/ttyUSB0")
    ap.add_argument("--wait", type=int, default=20, help="seconds to wait for re-enumeration (default 20)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--log-dir", default=".", help="where to write t3x_flash_*.log (default: current dir)")
    ap.add_argument("--allow-unknown-product", action="store_true",
                    help="recovery only: flash a station in bootloader mode whose bootloader "
                         "string has no product field")
    args = ap.parse_args(argv)

    sim = environment.simulated()
    log_dir = os.path.join(args.log_dir, "sim") if sim else args.log_dir     # never mix with real logs
    os.makedirs(log_dir, exist_ok=True)
    previous = latest_log(log_dir, include_simulated=sim)
    logger, logname = setup_logging(args.debug, log_dir)
    logger.info(f"Full log: {logname}")
    if sim:
        logger.info(f"{SIM_MARKER} ({environment.SIM_ENV} is set)")
    mm = None if sim else environment.modemmanager_active()
    if mm is not None:
        logger.debug(f"ModemManager active: {mm}")
    if previous:
        s = parse_log(previous)
        if s.outcome == "interrupted":
            logger.warning(f"Previous log {os.path.basename(previous)}: {s.describe()}")

    try:
        img = fwimage.load(args.file)
    except fwimage.ImageError as e:
        sys.exit(f"ERROR: {e}")

    console = Console(LogSink(logger))
    link = SerialLink(args.port, args.wait, emit=console)
    result = Flasher(img, link, emit=console, confirm=make_confirm(args.yes, bool(mm)),
                     allow_unknown_product=args.allow_unknown_product).run()
    if result.preflight is not None:          # something was asked of a station: keep a record
        try:
            history.append(log_dir, history.make_record(result, img, tool="t3x-update", log_path=logname,
                                                        simulated=sim, usb_serial=link.serial_number))
        except OSError as e:
            logger.warning(f"Could not write the flash history: {e}")
    if result.fatal:
        logger.debug(f"fatal: {result.message}")
        sys.exit(f"ERROR: {result.message}")
    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
