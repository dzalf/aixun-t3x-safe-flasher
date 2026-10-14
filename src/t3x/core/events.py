# SPDX-License-Identifier: GPL-2.0-or-later
"""Events emitted by the core. Front-ends (CLI, GUI) subscribe with a callable.

The core never prints and never asks questions: everything it wants to say
goes through `emit(event)`, and every decision it needs comes from a callback.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional


class Stage(str, enum.Enum):
    LOAD = "load"                # parse + validate the image
    CONNECT = "connect"          # find and open the station
    PREFLIGHT = "preflight"      # read identity/version, compare product
    CONFIRM = "confirm"          # waiting for the user
    BOOTLOADER = "bootloader"    # entering / confirming JC_boot
    START = "start"              # size + bootloader string -> update_jcxx
    TRANSFER = "transfer"        # 2048-byte chunks
    VERIFY = "verify"            # reconnect and read back the version
    DONE = "done"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class LogEvent:
    level: int                   # logging.DEBUG / INFO / WARNING / ERROR
    message: str


@dataclass
class StageEvent:
    stage: Stage
    detail: str = ""


@dataclass
class ProgressEvent:
    index: int                   # 1-based chunk number just acknowledged
    total: int
    bytes_done: int
    bytes_total: int

    @property
    def percent(self) -> int:
        return self.bytes_done * 100 // self.bytes_total if self.bytes_total else 0


@dataclass
class PortsEvent:
    tag: str
    ports: List["PortInfo"] = field(default_factory=list)  # noqa: F821 (core.link)
    opened: Optional[str] = None


Event = object
Emitter = Callable[[Event], None]


def null_emit(_event) -> None:
    pass


def log(emit: Emitter, level: int, message: str) -> None:
    emit(LogEvent(level, message))


debug = lambda e, m: log(e, logging.DEBUG, m)      # noqa: E731
info = lambda e, m: log(e, logging.INFO, m)        # noqa: E731
warning = lambda e, m: log(e, logging.WARNING, m)  # noqa: E731
error = lambda e, m: log(e, logging.ERROR, m)      # noqa: E731
