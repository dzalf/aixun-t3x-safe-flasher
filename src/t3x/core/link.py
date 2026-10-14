# SPDX-License-Identifier: GPL-2.0-or-later
"""Port discovery and the serial link used by the updater.

Behaviour (timeouts, settle delays, log wording) is ported 1:1 from
t3xupdate_safe.py; tests/test_golden.py proves the bytes on the wire match.

Discovery is injectable (`port_lister`) so the simulator and tests can supply
ports. Setting T3X_SIM_PORTS=<json file> makes the default lister read the
port list written by `t3x-sim`, so the real CLI/GUI can be run against it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional

import serial
from serial.tools import list_ports

from . import events as ev
from .protocol import BAUDRATE, FTDI_IDS, SERIAL_PREFIXES


class LinkError(Exception):
    """Discovery or connection failed (message is user-facing)."""


class LinkTimeout(LinkError):
    """The station did not (re)appear in time."""


try:                                   # POSIX: tcdrain/tcflush raise termios.error
    import termios
    _OS_IO_ERRORS: tuple = (OSError, termios.error)
except ImportError:                    # pragma: no cover (non-POSIX)
    _OS_IO_ERRORS = (OSError,)

# Everything pyserial or the OS can raise when the USB device disappears.
# termios.error is NOT a SerialException: pyserial's flush() calls tcdrain()
# directly, and on a vanished device that raises termios.error(EIO). Found on
# the Raspberry Pi 5 test run (session 01a).
IO_ERRORS = (serial.SerialException,) + _OS_IO_ERRORS


class DeviceLost(serial.SerialException):
    """The station vanished from USB during I/O (expected at reset points)."""


@dataclass
class PortInfo:
    device: str
    vid: Optional[int] = None
    pid: Optional[int] = None
    serial_number: Optional[str] = None
    product: Optional[str] = None
    manufacturer: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None

    @property
    def is_t3x(self) -> bool:
        return bool(self.serial_number and self.serial_number.startswith(SERIAL_PREFIXES))

    @property
    def is_ftdi_id(self) -> bool:
        return (self.vid, self.pid) == FTDI_IDS

    def short(self) -> str:
        vp = f"{self.vid:04X}:{self.pid:04X}" if self.vid is not None else "----:----"
        return f"{self.device} {vp} SER={self.serial_number} PROD={self.product}"


def _from_pyserial(p) -> PortInfo:
    return PortInfo(p.device, p.vid, p.pid, p.serial_number, p.product,
                    p.manufacturer, p.location, getattr(p, "description", None))


def system_port_lister() -> List[PortInfo]:
    sim = os.environ.get("T3X_SIM_PORTS")
    if sim:
        try:
            with open(sim) as f:
                return [PortInfo(**d) for d in json.load(f)]
        except (OSError, ValueError):
            return []
    return [_from_pyserial(p) for p in list_ports.comports()]


def write_sim_ports(path: str, ports: List[PortInfo]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump([asdict(p) for p in ports], f)
    os.replace(tmp, path)


@dataclass
class Timing:
    """All delays in one place. Defaults equal t3xupdate_safe.py."""
    serial_timeout: float = 0.05
    settle: float = 0.3          # after opening a freshly enumerated port
    poll: float = 0.25           # between discovery attempts
    reply_timeout: float = 3.0   # no first byte -> give up
    chunk_timeout: float = 5.0
    idle: float = 0.1            # line quiet this long after data -> reply complete
    after_reset: float = 1.0     # before reconnecting into the bootloader
    boot_confirm_tries: int = 3
    boot_confirm_gap: float = 0.5
    after_flash: float = 2.0
    verify_tries: int = 5
    verify_gap: float = 1.0

    @classmethod
    def fast(cls) -> "Timing":
        """For tests/simulator: same logic, shorter waits."""
        return cls(settle=0.02, poll=0.02, reply_timeout=1.0, chunk_timeout=2.0, idle=0.03,
                   after_reset=0.05, boot_confirm_gap=0.05, after_flash=0.05, verify_gap=0.05)


class SerialLink:
    def __init__(self, port: Optional[str] = None, wait: float = 20,
                 emit: ev.Emitter = ev.null_emit,
                 port_lister: Callable[[], List[PortInfo]] = system_port_lister,
                 timing: Optional[Timing] = None):
        self.forced_port = port
        self.wait = wait
        self.emit = emit
        self.port_lister = port_lister
        self.t = timing or Timing()
        self.ser: Optional[serial.Serial] = None
        self.device: Optional[str] = None
        self.serial_number: Optional[str] = None   # USB serial of the first port opened

    # ------------------------------------------------------------ discovery
    def find_port(self, allow_fallback: bool = False) -> Optional[str]:
        ports = self.port_lister()
        if self.forced_port:
            if any(p.device == self.forced_port for p in ports):
                return self.forced_port
            if not allow_fallback:
                return None
            # Reconnecting after a reset: the station re-enumerates under a NEW tty
            # (ttyUSB0 -> ttyUSB1), so a forced path can't be reused. Follow the same
            # USB serial number instead; else fall through to normal discovery.
            # (The original script waited for the old path and timed out.)
            if self.serial_number:
                same = [p for p in ports if p.serial_number == self.serial_number]
                if len(same) == 1:
                    ev.info(self.emit, f"{self.forced_port} is gone; following serial "
                                       f"{self.serial_number} to {same[0].device}")
                    return same[0].device
        hits = [p for p in ports if p.is_t3x]
        if len(hits) > 1:
            raise LinkError("multiple T3x attached.")
        if hits:
            return hits[0].device
        if allow_fallback:
            ftdi = [p for p in ports if p.is_ftdi_id]
            if len(ftdi) == 1:
                ev.warning(self.emit, f"No JCID serial found; using the only 0403:6001 device: "
                                      f"{ftdi[0].device} SER={ftdi[0].serial_number}")
                return ftdi[0].device
        return None

    def snapshot(self, tag: str, opened: Optional[str] = None) -> None:
        ports = self.port_lister()
        for p in ports:
            if p.vid is not None:
                ev.debug(self.emit, f"[{tag}] {p.device} {p.vid:04X}:{p.pid:04X} "
                                    f"SER={p.serial_number} PROD={p.product}")
        self.emit(ev.PortsEvent(tag, ports, opened))

    # ------------------------------------------------------------ connection
    def close(self) -> None:
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def connect(self, allow_fallback: bool = False, tag: str = "connect") -> str:
        self.close()
        deadline = time.monotonic() + self.wait
        while time.monotonic() < deadline:
            dev = self.find_port(allow_fallback)
            if dev:
                try:
                    self.ser = serial.Serial(dev, baudrate=BAUDRATE, timeout=self.t.serial_timeout)
                    time.sleep(self.t.settle)
                    self.ser.reset_input_buffer()
                    self.device = dev
                    if self.serial_number is None:
                        self.serial_number = next((p.serial_number for p in self.port_lister()
                                                   if p.device == dev), None)
                    self.snapshot(tag, dev)
                    ev.debug(self.emit, f"Opened {dev}")
                    return dev
                except IO_ERRORS as e:          # vanished again while settling: keep polling
                    ev.debug(self.emit, f"open {dev} failed: {e}")
                    self.close()
            time.sleep(self.t.poll)
        self.snapshot(tag + "-timeout")
        raise LinkTimeout(f"station did not re-appear within {self.wait} s. "
                          "It is probably sitting in the bootloader: do NOT power it off, "
                          "re-run this script.")

    # ------------------------------------------------------------ I/O
    def transfer(self, data: bytes, timeout: Optional[float] = None, idle: Optional[float] = None) -> bytes:
        """Write `data`, read until the line has been idle. Raises DeviceLost."""
        timeout = self.t.reply_timeout if timeout is None else timeout
        idle = self.t.idle if idle is None else idle
        shown = data[:32] + (b"..." if len(data) > 32 else b"")
        ev.debug(self.emit, f"TX ({len(data)}): {shown!r}")
        try:
            self.ser.reset_input_buffer()
            self.ser.write(data)
            self.ser.flush()
        except IO_ERRORS as e:
            raise DeviceLost(f"device lost while writing: {e}") from e
        t0 = time.monotonic()
        rx = bytearray()
        last = None
        while True:
            try:
                chunk = self.ser.read(256)
            except IO_ERRORS as e:
                raise DeviceLost(f"device lost while reading: {e}") from e
            now = time.monotonic()
            if chunk:
                rx += chunk
                last = now
            elif rx and now - last > idle:
                break
            elif not rx and now - t0 > timeout:
                break
        rx = bytes(rx).rstrip(b"\x00")
        ev.debug(self.emit, f"RX ({len(rx)}) after {(time.monotonic() - t0) * 1000:.0f} ms: {rx!r}")
        return rx
