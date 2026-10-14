# SPDX-License-Identifier: GPL-2.0-or-later
"""Flash log files: writing (same format as t3xupdate_safe.py) and parsing.

Parsing lets a front-end tell the user where an interrupted update stopped,
e.g. "stopped at chunk 31/82 (device lost)". Logs written by the original
t3xupdate_safe.py parse the same way.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from . import events as ev

FILE_FMT = "%(asctime)s.%(msecs)03d %(levelname)s: %(message)s"
FILE_DATEFMT = "%H:%M:%S"
NAME_PATTERN = "t3x_flash_%Y%m%d_%H%M%S.log"


def new_log_path(directory: str = ".") -> str:
    return os.path.join(directory, time.strftime(NAME_PATTERN))


class LogSink:
    """Routes core LogEvents into a `logging.Logger` (file + optional console)."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def __call__(self, event) -> None:
        if isinstance(event, ev.LogEvent):
            self.logger.log(event.level, event.message)


def file_handler(path: str) -> logging.Handler:
    h = logging.FileHandler(path)
    h.setLevel(logging.DEBUG)
    h.setFormatter(logging.Formatter(FILE_FMT, FILE_DATEFMT))
    return h


# ---------------------------------------------------------------- parsing
_ACK = re.compile(r"RX \(\d+\) after \d+ ms: b'ack_jcxx'")
_TOTAL = re.compile(r"Update file: (\S+) v(\S+) \((\d+) bytes")
_LOST = re.compile(r"(Device lost|Bad ACK) at chunk (\d+)/(\d+)")


@dataclass
class LogSummary:
    path: str
    product: Optional[str] = None
    version: Optional[str] = None
    image_size: Optional[int] = None
    started_transfer: bool = False
    chunks_acked: int = 0
    n_chunks: Optional[int] = None
    outcome: str = "unknown"          # success | interrupted | failed-before-write | aborted | unknown
    failure: Optional[str] = None

    def describe(self) -> str:
        if self.outcome == "success":
            return f"completed: {self.product} v{self.version}"
        if self.outcome == "interrupted":
            where = f"chunk {self.chunks_acked + 1}/{self.n_chunks}" if self.n_chunks else "during transfer"
            return f"stopped at {where}" + (f" ({self.failure})" if self.failure else "")
        if self.outcome == "failed-before-write":
            return "failed before anything was written" + (f" ({self.failure})" if self.failure else "")
        if self.outcome == "aborted":
            return "aborted by user before writing"
        return "unknown outcome"


def parse_log(path: str) -> LogSummary:
    s = LogSummary(path)
    with open(path, errors="replace") as f:
        lines = f.read().splitlines()
    in_transfer = False
    for line in lines:
        m = _TOTAL.search(line)
        if m:
            s.product, s.version, s.image_size = m.group(1), m.group(2), int(m.group(3))
            s.n_chunks = (s.image_size + 2047) // 2048
        if "Sending firmware..." in line:
            s.started_transfer = in_transfer = True
        elif in_transfer and _ACK.search(line):
            s.chunks_acked += 1
        m = _LOST.search(line)
        if m:
            s.failure = "device lost" if m.group(1) == "Device lost" else "bad ACK"
            s.n_chunks = int(m.group(3))
        if "Update successful" in line:
            s.outcome = "success"
        elif "Aborted by user" in line:
            s.outcome = "aborted"
    if s.outcome == "unknown":
        if s.started_transfer:
            s.outcome = "interrupted"
        elif any(" ERROR: " in l for l in lines):
            s.outcome = "failed-before-write"
            s.failure = next(l.split(" ERROR: ", 1)[1] for l in lines if " ERROR: " in l)
    return s


SIM_MARKER = "SIMULATED STATION"


def is_simulated_log(path: str) -> bool:
    """Logs from the simulator: marked since session 03; older ones name a /tmp/t3x-sim-* port."""
    try:
        with open(path, errors="replace") as f:
            head = f.read(4096)
    except OSError:
        return False
    return SIM_MARKER in head or "t3x-sim-" in head


def latest_log(directory: str = ".", include_simulated: bool = False) -> Optional[str]:
    """Newest flash log in `directory` (not recursive). Simulator logs are skipped unless asked for,
    so a simulated failure is never presented as the real station's last update."""
    logs = sorted(glob.glob(os.path.join(directory, "t3x_flash_*.log")))
    for path in reversed(logs):
        if include_simulated or not is_simulated_log(path):
            return path
    return None
