# SPDX-License-Identifier: GPL-2.0-or-later
"""Background jobs. Serial I/O never runs on the GUI thread.

Each job is a QObject moved to its own QThread; results come back through
Qt signals, which Qt delivers on the GUI thread.
"""

from __future__ import annotations

import itertools
import logging
import threading
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core import environment, history
from ..core import events as ev
from ..core.flasher import Flasher, Preflight
from ..core.image import FirmwareImage
from ..core.link import SerialLink
from ..core.logfile import SIM_MARKER, LogSink, file_handler, new_log_path
from ..core.probe import PortInfo, run_probe

_ids = itertools.count(1)


def start(job: QObject, parent: QObject) -> QThread:
    """Run job.run() in a new QThread; the thread quits when job.finished fires."""
    th = QThread(parent)
    job.moveToThread(th)
    th.started.connect(job.run)
    job.finished.connect(th.quit)
    th.finished.connect(th.deleteLater)
    th.start()
    return th


class ProbeJob(QObject):
    """Read-only probe (whitelisted queries only, see core/probe.py)."""

    reply = Signal(object)        # probe.Reply as it arrives
    progress = Signal(int, int)   # queries done, total
    finished = Signal(object)     # ProbeReport, or the Exception that stopped it

    def __init__(self, port: PortInfo, image: Optional[FirmwareImage] = None, reader_test: int = 10,
                 repeat: int = 3, listen_s: float = 0.5):
        super().__init__()
        self.port, self.image = port, image
        self.reader_test, self.repeat, self.listen_s = reader_test, repeat, listen_s
        self._cancel = threading.Event()

    def cancel(self):
        """Thread-safe: the probe stops before its next query (at most one reply timeout)."""
        self._cancel.set()

    @Slot()
    def run(self):
        try:
            rep = run_probe(self.port, repeat=self.repeat, reader_test=self.reader_test, image=self.image,
                            listen_s=self.listen_s, on_reply=self.reply.emit,
                            cancelled=self._cancel.is_set, on_progress=self.progress.emit)
            self.finished.emit(rep)
        except Exception as e:          # noqa: BLE001 - reported to the user, never swallowed
            self.finished.emit(e)


class FuncJob(QObject):
    """Run any blocking function off the GUI thread (network requests, file scans)."""

    finished = Signal(object)     # the function's return value, or the Exception it raised

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:          # noqa: BLE001 - shown to the user
            self.finished.emit(e)


@dataclass
class Expected:
    """What the user verified. The flash only proceeds if the station still matches."""
    identity: bytes
    raw_version: bytes


class FlashJob(QObject):
    event = Signal(object)        # core events (LogEvent, StageEvent, ProgressEvent, PortsEvent)
    finished = Signal(object)     # FlashResult, or Exception

    def __init__(self, image: FirmwareImage, expected: Expected, log_dir: str, wait: float = 20,
                 port: Optional[str] = None, allow_unknown_product: bool = False, link_factory=None,
                 simulated: bool = False):
        super().__init__()
        self.simulated = simulated
        self.history_error: Optional[str] = None
        self.image, self.expected = image, expected
        self.log_dir, self.wait, self.port = log_dir, wait, port
        self.allow_unknown_product = allow_unknown_product
        self.link_factory = link_factory        # tests inject a simulator-backed link
        self.log_path = new_log_path(log_dir)
        self.mismatch: Optional[str] = None

    def _confirm(self, pf: Preflight) -> bool:
        """The user confirmed in the GUI before the job started. Re-check that the
        station is still the one that was verified (same identity and version string)."""
        if pf.identity != self.expected.identity or pf.station.raw != self.expected.raw_version:
            self.mismatch = (f"Station changed since it was verified: expected {self.expected.identity!r} "
                             f"{self.expected.raw_version!r}, now {pf.identity!r} {pf.station.raw!r}. "
                             "Nothing was written. Verify again.")
            self.event.emit(ev.LogEvent(logging.ERROR, self.mismatch))
            return False
        return True

    @Slot()
    def run(self):
        logger = logging.getLogger(f"t3x.gui.flash{next(_ids)}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        fh = file_handler(self.log_path)
        logger.addHandler(fh)
        sink = LogSink(logger)

        def emit(e):
            sink(e)
            self.event.emit(e)

        try:
            emit(ev.LogEvent(logging.INFO, f"Full log: {self.log_path}"))
            if self.simulated:
                emit(ev.LogEvent(logging.INFO, SIM_MARKER))
            else:
                mm = environment.modemmanager_active()
                if mm is not None:
                    emit(ev.LogEvent(logging.DEBUG, f"ModemManager active: {mm}"))
            link = (self.link_factory(emit) if self.link_factory
                    else SerialLink(self.port, self.wait, emit=emit))
            result = Flasher(self.image, link, emit=emit, confirm=self._confirm,
                             allow_unknown_product=self.allow_unknown_product).run()
            if result.preflight is not None:
                try:
                    history.append(self.log_dir, history.make_record(
                        result, self.image, tool="t3x-gui", log_path=self.log_path,
                        simulated=self.simulated, usb_serial=link.serial_number))
                except OSError as e:
                    self.history_error = str(e)
            self.finished.emit(result)
        except Exception as e:          # noqa: BLE001
            emit(ev.LogEvent(logging.ERROR, f"Unexpected error: {e!r}"))
            self.finished.emit(e)
        finally:
            logger.removeHandler(fh)
            fh.close()
