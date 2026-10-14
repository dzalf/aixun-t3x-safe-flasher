# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only station probe. It can never enter the bootloader or write firmware.

Only JC_identity and JC_version are sent (plus JC_hardware when explicitly
allowed). Every write goes through `_guard()`, which refuses anything else.
In particular the version string is never echoed back: that echo is what
resets the station into the bootloader.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import serial

from .image import Check, FirmwareImage
from .link import IO_ERRORS, DeviceLost, PortInfo, system_port_lister
from .protocol import (BAUDRATE, CMD_HARDWARE, CMD_IDENTITY, CMD_VERSION, ID_APP, ID_BOOT,
                       READ_ONLY_COMMANDS, VersionInfo, parse_version)


class ProbeError(Exception):
    pass


class NotAllowed(ProbeError):
    pass


class PortUnavailable(ProbeError):
    """The port exists but cannot be opened yet (busy, permissions not applied yet, ...)."""


class NoReply(ProbeError):
    """The port opened but the station did not answer the first query."""


class ProbeCancelled(ProbeError):
    pass


# ---------------------------------------------------------------- discovery
def find_station(explicit: Optional[str] = None,
                 port_lister: Callable[[], List[PortInfo]] = system_port_lister,
                 wait: float = 0.0) -> PortInfo:
    """Locate the station. With `wait` > 0, keep looking (e.g. while it re-enumerates)."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return _find_once(explicit, port_lister)
        except ProbeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _find_once(explicit, port_lister) -> PortInfo:
    ports = port_lister()
    if explicit:
        for p in ports:
            if p.device == explicit:
                return p
        raise ProbeError(f"{explicit} not found.")
    hits = [p for p in ports if p.is_t3x]
    if not hits:
        from .protocol import SERIAL_PREFIXES
        raise ProbeError("No T3x found (no port with serial number starting "
                         f"{SERIAL_PREFIXES}).")
    if len(hits) > 1:
        raise ProbeError(f"Multiple T3x attached: {[p.device for p in hits]}")
    return hits[0]


def _read_sysfs(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def usb_details(p: PortInfo, sysfs_root: str = "/sys") -> List[Tuple[str, str]]:
    """(label, value) rows, same labels and order as the original probe."""
    rows = [("Port", p.device),
            ("VID:PID", f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "n/a"),
            ("Serial number", str(p.serial_number)),
            ("Manufacturer", str(p.manufacturer)),
            ("Product", str(p.product)),
            ("Location", str(p.location))]
    name = os.path.basename(p.device)
    dev_link = f"{sysfs_root}/class/tty/{name}/device"
    if os.path.exists(dev_link):
        usbdev = os.path.dirname(os.path.dirname(os.path.realpath(dev_link)))
        for attr, label in [("bcdDevice", "bcdDevice (chip rev)"), ("version", "USB spec"),
                            ("speed", "Speed (Mbit/s)"), ("bMaxPower", "bMaxPower"),
                            ("bNumConfigurations", "Configurations")]:
            v = _read_sysfs(os.path.join(usbdev, attr))
            if v is not None:
                rows.append((label, v))
        drv = os.path.join(dev_link, "driver")
        if os.path.exists(drv):
            rows.append(("Kernel driver", os.path.basename(os.path.realpath(drv))))
        lat = _read_sysfs(f"{sysfs_root}/bus/usb-serial/devices/{name}/latency_timer")
        if lat is not None:
            rows.append(("FTDI latency", f"{lat} ms"))
    return rows


# ---------------------------------------------------------------- session
@dataclass
class Reply:
    round: int
    command: bytes
    data: bytes
    latency_ms: Optional[float]


class ProbeSession:
    """Owns the serial port; enforces the read-only whitelist."""

    def __init__(self, device: str, allow_hardware: bool = False, idle: float = 0.15,
                 timeout: float = 3.0, cancelled: Optional[Callable[[], bool]] = None):
        self.cancelled = cancelled
        self.allowed = list(READ_ONLY_COMMANDS) + ([CMD_HARDWARE] if allow_hardware else [])
        self.idle, self.timeout = idle, timeout
        self.sent: List[bytes] = []          # audit trail of every write
        try:
            self.ser = serial.Serial(device, baudrate=BAUDRATE, timeout=0.1)
        except IO_ERRORS as e:
            raise PortUnavailable(f"cannot open {device}: {e}") from e

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _check_cancel(self) -> None:
        if self.cancelled and self.cancelled():
            raise ProbeCancelled("probe cancelled")

    def _guard(self, data: bytes) -> None:
        if data not in self.allowed:
            raise NotAllowed(f"Refusing to send non-whitelisted data: {data!r}")
        self.sent.append(data)

    def query(self, data: bytes) -> Tuple[bytes, Optional[float]]:
        """Write a whitelisted query; read until the line is idle (robust reader)."""
        self._guard(data)
        try:
            return self._query(data)
        except IO_ERRORS as e:
            raise DeviceLost(f"station disconnected during the probe: {e}") from e

    def _query(self, data: bytes) -> Tuple[bytes, Optional[float]]:
        ser = self.ser
        ser.reset_input_buffer()
        t0 = time.monotonic()
        ser.write(data)
        ser.flush()
        rx = bytearray()
        first_at = last_at = None
        while True:
            self._check_cancel()
            now = time.monotonic()
            n = ser.in_waiting
            if n:
                rx += ser.read(n)
                last_at = now
                if first_at is None:
                    first_at = now
            elif rx and now - last_at > self.idle:
                break
            elif not rx and now - t0 > self.timeout:
                break
            time.sleep(0.005)
        return bytes(rx), ((first_at - t0) * 1000 if first_at else None)

    def query_original_reader(self, data: bytes) -> bytes:
        """Same query, read with the upstream updater's read(1) + read_all() method."""
        self._guard(data)
        try:
            return self._query_original(data)
        except IO_ERRORS as e:
            raise DeviceLost(f"station disconnected during the probe: {e}") from e

    def _query_original(self, data: bytes) -> bytes:
        ser = self.ser
        ser.reset_input_buffer()
        old = ser.timeout
        ser.timeout = 3
        try:
            ser.write(data)
            rx = ser.read(1)
            rx += ser.read_all().rstrip(b"\x00")
        finally:
            ser.timeout = old
        return rx

    def listen(self, seconds: float = 1.0) -> bytes:
        try:
            return self._listen(seconds)
        except IO_ERRORS as e:
            raise DeviceLost(f"station disconnected during the probe: {e}") from e

    def _listen(self, seconds: float) -> bytes:
        self.ser.reset_input_buffer()
        end = time.monotonic() + seconds
        rx = bytearray()
        while time.monotonic() < end:
            self._check_cancel()
            n = self.ser.in_waiting
            if n:
                rx += self.ser.read(n)
            time.sleep(0.01)
        return bytes(rx)


# ---------------------------------------------------------------- report
@dataclass
class ProbeReport:
    port: PortInfo
    usb: List[Tuple[str, str]] = field(default_factory=list)
    unsolicited: bytes = b""
    replies: List[Reply] = field(default_factory=list)
    reader_test_n: int = 0
    reader_mismatches: List[Tuple[int, bytes, bytes]] = field(default_factory=list)
    image: Optional[FirmwareImage] = None
    hardware_allowed: bool = False
    sent: List[bytes] = field(default_factory=list)

    def answers(self, cmd: bytes) -> List[bytes]:
        return [r.data for r in self.replies if r.command == cmd]

    @property
    def identity(self) -> bytes:
        ids = self.answers(CMD_IDENTITY)
        return ids[0].rstrip(b"\x00") if ids else b""

    @property
    def version(self) -> VersionInfo:
        v = self.answers(CMD_VERSION)
        return parse_version(v[0] if v else b"")

    @property
    def hardware(self) -> Optional[bytes]:
        h = self.answers(CMD_HARDWARE)
        return h[0] if h else None

    @property
    def latencies(self) -> List[float]:
        return [r.latency_ms for r in self.replies if r.latency_ms is not None]

    @property
    def reader_total(self) -> int:
        return self.reader_test_n * len(READ_ONLY_COMMANDS)

    def checks(self) -> List[Check]:
        ids, vers = self.answers(CMD_IDENTITY), self.answers(CMD_VERSION)
        v = self.version
        out = [
            Check("Station replies to JC_identity", bool(ids and ids[0]), self.identity.decode(errors="replace")),
            Check("Identity replies consistent", len(set(ids)) == 1 and ids[0] != b"", f"{len(ids)} replies"),
            Check("Station replies to JC_version", bool(vers and vers[0]), v.raw.decode(errors="replace")),
            Check("Version replies consistent", len(set(vers)) == 1 and vers[0] != b"", f"{len(vers)} replies"),
            Check("Station in application mode (JC_User)", self.identity == ID_APP, self.identity.decode(errors="replace")),
        ]
        if self.reader_test_n:
            bad = len(self.reader_mismatches)
            out.append(Check("Updater's read method returns complete replies", bad == 0,
                             f"{self.reader_total - bad}/{self.reader_total} complete"))
        if self.image is not None:
            img = self.image
            out.append(Check("Update file valid (magic/size/CRC/vectors)", img.valid,
                             "; ".join(c.detail for c in img.checks if not c.ok) or "all OK"))
            out.append(Check("Update product matches station",
                             bool(v.product and img.product and v.product == img.product),
                             f"file {img.product_str} / station {v.product_str}"))
        return out

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks())

    @property
    def mode(self) -> str:
        return {ID_APP: "APPLICATION (normal firmware running)",
                ID_BOOT: "BOOTLOADER (station is already in update mode)"}.get(self.identity, "UNKNOWN")

    def to_dict(self) -> Dict:
        v = self.version
        return {
            "port": self.port.device, "usb": dict(self.usb),
            "identity": self.identity.decode(errors="replace"),
            "version_string": v.raw.decode(errors="replace"),
            "product": v.product_str, "firmware": v.version_str,
            "hardware": self.hardware.decode(errors="replace") if self.hardware else None,
            "latency_ms": {"min": min(self.latencies, default=None), "max": max(self.latencies, default=None)},
            "reader_test": {"n": self.reader_test_n, "mismatches": len(self.reader_mismatches)},
            "image": None if self.image is None else {
                "path": self.image.path, "product": self.image.product_str,
                "version": self.image.version_str, "size": self.image.size,
                "crc": f"{self.image.crc_calc:04X}", "valid": self.image.valid},
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks()],
            "ok": self.ok,
            "sent": [s.decode(errors="replace") for s in self.sent],
        }


def run_probe(port: PortInfo, repeat: int = 3, reader_test: int = 0, allow_hardware: bool = False,
              image: Optional[FirmwareImage] = None, listen_s: float = 1.0,
              on_reply: Optional[Callable[[Reply], None]] = None,
              cancelled: Optional[Callable[[], bool]] = None,
              on_progress: Optional[Callable[[int, int], None]] = None) -> ProbeReport:
    """Non-interactive probe for GUI/automation. Same traffic as the CLI when the station answers.

    Fails fast instead of running every query against a silent station: if the very first
    query gets no reply, NoReply is raised after one timeout (about 3 s). `cancelled` is
    checked between queries (ProbeCancelled); `on_progress(done, total)` after each query.
    """
    rep = ProbeReport(port, usb_details(port), image=image, hardware_allowed=allow_hardware)

    def check_cancel():
        if cancelled and cancelled():
            raise ProbeCancelled("probe cancelled")

    with ProbeSession(port.device, allow_hardware, cancelled=cancelled) as s:
        total = repeat * len(s.allowed) + reader_test * len(READ_ONLY_COMMANDS)
        done = 0

        def step():
            nonlocal done
            done += 1
            if on_progress:
                on_progress(done, total)

        time.sleep(0.2)
        check_cancel()
        rep.unsolicited = s.listen(listen_s)
        for i in range(repeat):
            for cmd in s.allowed:
                check_cancel()
                data, lat = s.query(cmd)
                if not rep.replies and not data:
                    raise NoReply(f"{port.device} is on USB, but the station did not answer "
                                  f"{cmd.decode()} within {s.timeout:.0f} s")
                r = Reply(i + 1, cmd, data, lat)
                rep.replies.append(r)
                step()
                if on_reply:
                    on_reply(r)
            time.sleep(0.2)
        if reader_test:
            rep.reader_test_n = reader_test
            ref = {c: rep.answers(c)[0] for c in READ_ONLY_COMMANDS}
            for i in range(reader_test):
                for cmd in READ_ONLY_COMMANDS:
                    check_cancel()
                    rx = s.query_original_reader(cmd)
                    if rx != ref[cmd]:
                        rep.reader_mismatches.append((i + 1, cmd, rx))
                    step()
                    time.sleep(0.05)
        rep.sent = list(s.sent)
    return rep
