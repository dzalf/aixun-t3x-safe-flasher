# SPDX-License-Identifier: GPL-2.0-or-later
"""Simulated AiXun T3x station on a pseudo-terminal.

It speaks the protocol observed on a real T3BS (1.06 -> 1.16, Oct 2026),
including the USB drop when entering the bootloader and after the last
chunk, and re-enumeration under a new device path (ttyUSB0 -> ttyUSB1).
Fault scenarios cover interrupted transfers, bad ACKs and slow re-enumeration.

Programmatic use (tests):
    with SimStation(Scenario()) as sim:
        link = SerialLink(port_lister=sim.port_lister, ...)

Interactive use (develop the CLI/GUI without an iron):
    t3x-sim --fail-at-chunk 31           # in one terminal
    export T3X_SIM_PORTS=/tmp/t3x-sim-ports.json
    t3x-probe ; t3x-update FILE          # in another
"""

from __future__ import annotations

import argparse
import os
import pty
import select
import shutil
import tempfile
import threading
import time
import tty
from dataclasses import dataclass
from typing import List, Optional

from ..core.link import PortInfo, write_sim_ports


@dataclass
class Scenario:
    product: bytes = b"T3BS"
    app_version: bytes = b"1.06"
    usb_serial: str = "JCID_T3B_SIM0000001"
    usb_product: str = "JCID_T3B"
    bootloader_string: bytes = b"00160000JC_M_T3BS_version1.01"
    start_in_bootloader: bool = False
    reset_ack: bool = False          # real unit: no JC_reset, just drops off USB
    ack_last_chunk: bool = False     # real unit: drops off USB instead of ACKing
    reenum_delay: float = 0.3        # seconds absent from USB after a reset
    fail_at_chunk: Optional[int] = None   # 1-based: device lost, stays in bootloader
    fault_once: bool = True          # like a real cable pull: the injected fault happens on the first transfer only
    bad_ack_at_chunk: Optional[int] = None
    no_start_ack: bool = False
    verify_comes_back_in_boot: bool = False
    split_replies: bool = False      # reply arrives in two pieces 30 ms apart
    reply_delay: float = 0.005
    hardware_reply: Optional[bytes] = None   # answer to JC_hardware (None = silent)
    wake_delay: float = 0.0          # after plug(): on USB but silent this long (firmware/USB bridge not ready)


@dataclass
class SimLogEntry:
    t: float
    kind: str
    detail: str = ""


class SimStation:
    def __init__(self, scenario: Optional[Scenario] = None, ports_file: Optional[str] = None):
        self.sc = scenario or Scenario()
        self.ports_file = ports_file
        self.mode = "boot" if self.sc.start_in_bootloader else "app"
        self.product = self.sc.product
        self.version = self.sc.app_version
        self.rx_stream = bytearray()          # every byte the host wrote, across reconnects
        self.frames: List[bytes] = []         # the same, split into commands / chunks
        self.log: List[SimLogEntry] = []
        self.flashed: Optional[bytes] = None
        self._xfer_expected = 0
        self._xfer_buf = bytearray()
        self._chunk_index = 0
        self._received = bytearray()
        self._master: Optional[int] = None
        self._slave: Optional[int] = None
        self.device: Optional[str] = None
        self.enumerations = 0
        # Each enumeration gets a NEW name (ttyUSB0, ttyUSB1, ...) like the real station,
        # via symlinks to the pty; pts numbers alone may be reused by the kernel.
        self._alias_dir = tempfile.mkdtemp(prefix="t3x-sim-")
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._awake_at = 0.0

    # ------------------------------------------------------------ lifecycle
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()

    def start(self, attached: bool = True):
        """attached=False: the station starts unplugged; call plug() later (hot-plug)."""
        if attached:
            self._attach()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="t3x-sim")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._detach()
        shutil.rmtree(self._alias_dir, ignore_errors=True)

    def plug(self, wake_delay: Optional[float] = None):
        """Hot-plug: appear on USB now; stay silent for wake_delay seconds (default: scenario)."""
        delay = self.sc.wake_delay if wake_delay is None else wake_delay
        self._awake_at = time.monotonic() + delay
        self._attach()

    def unplug(self):
        self._detach()

    def _note(self, kind, detail=""):
        self.log.append(SimLogEntry(time.monotonic(), kind, detail))

    def _attach(self):
        m, s = pty.openpty()
        tty.setraw(s)
        alias = os.path.join(self._alias_dir, f"ttyUSB{self.enumerations}")
        os.symlink(os.ttyname(s), alias)
        with self._lock:
            self._master, self._slave = m, s
            self.device = alias
            self.enumerations += 1
        self._note("attach", f"{self.device} mode={self.mode}")
        self._publish()

    def _detach(self):
        with self._lock:
            for fd in (self._master, self._slave):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self._master = self._slave = None
            if self.device:
                try:
                    os.remove(self.device)
                except OSError:
                    pass
            self.device = None
        self._note("detach")
        self._publish()

    def _reenumerate(self, new_mode: str):
        # Switch state BEFORE dropping off USB: the host can observe the drop
        # immediately, and anything it then reads from the station must already
        # reflect the new mode (a real station has no such window).
        self.mode = new_mode
        self._detach()
        time.sleep(self.sc.reenum_delay)
        if not self._stop.is_set():
            self._attach()

    # ------------------------------------------------------------ discovery
    def port_lister(self) -> List[PortInfo]:
        with self._lock:
            if self.device is None:
                return []
            return [PortInfo(self.device, 0x0403, 0x6001, self.sc.usb_serial, self.sc.usb_product,
                             "JCID", "sim", self.sc.usb_product)]

    def _publish(self):
        if self.ports_file:
            write_sim_ports(self.ports_file, self.port_lister())

    # ------------------------------------------------------------ I/O
    def _reply(self, data: bytes):
        time.sleep(self.sc.reply_delay)
        m = self._master
        if m is None:
            return
        try:
            if self.sc.split_replies and len(data) > 2:
                os.write(m, data[:len(data) // 2])
                time.sleep(0.03)
                os.write(m, data[len(data) // 2:])
            else:
                os.write(m, data)
        except OSError:
            pass

    def _loop(self):
        buf = bytearray()
        while not self._stop.is_set():
            m = self._master
            if m is None:
                time.sleep(0.01)
                continue
            try:
                r, _, _ = select.select([m], [], [], 0.05)
            except (OSError, ValueError):
                continue
            if not r:
                continue
            try:
                data = os.read(m, 65536)
            except OSError:
                time.sleep(0.01)      # host side not open yet / closed
                continue
            if not data:
                continue
            self.rx_stream += data
            if self.mode == "xfer":
                self._xfer_buf += data
                self._drain_xfer()
                continue
            buf += data
            # commands arrive as one burst; wait for the line to go quiet
            while True:
                r, _, _ = select.select([m], [], [], 0.01)
                if not r:
                    break
                try:
                    more = os.read(m, 65536)
                except OSError:
                    break
                self.rx_stream += more
                buf += more
            cmd, buf = bytes(buf), bytearray()
            self._command(cmd)

    def _version_string(self) -> bytes:
        return b"JC_M_" + self.product + b"_version" + self.version

    def _command(self, cmd: bytes):
        self.frames.append(cmd)
        self._note("rx", cmd[:40].decode(errors="replace"))
        if time.monotonic() < self._awake_at:
            self._note("ignored-waking", repr(cmd[:40]))
            return
        if cmd == b"JC_identity":
            self._reply(b"JC_User" if self.mode == "app" else b"JC_boot")
        elif cmd == b"JC_version":
            self._reply(self._version_string() if self.mode == "app" else self.sc.bootloader_string)
        elif cmd == b"JC_hardware" and self.mode == "app":
            if self.sc.hardware_reply:
                self._reply(self.sc.hardware_reply)
        elif self.mode == "app" and cmd == self._version_string():
            self._note("reset", "entering bootloader")
            if self.sc.reset_ack:
                self._reply(b"JC_reset")
                time.sleep(0.02)
            self._reenumerate("boot")
        elif self.mode == "boot" and cmd.startswith(b"0x") and len(cmd) >= 10:
            try:
                size = int(cmd[2:10], 16)
            except ValueError:
                self._note("bad-start", repr(cmd))
                return
            if self.sc.no_start_ack:
                self._note("start-ignored")
                return
            self._xfer_expected, self._xfer_buf, self._chunk_index = size, bytearray(), 0
            self.flashed = None
            self._received = bytearray()
            self.mode = "xfer"
            self._note("start", f"{size} bytes")
            self._reply(b"update_jcxx")
        else:
            self._note("ignored", repr(cmd[:40]))

    def _drain_xfer(self):
        while self.mode == "xfer":
            remaining = self._xfer_expected - len(self._received)
            need = min(2048, remaining)
            if len(self._xfer_buf) < need:
                return
            chunk = bytes(self._xfer_buf[:need])
            del self._xfer_buf[:need]
            self.frames.append(chunk)
            self._received += chunk
            self._chunk_index += 1
            k = self._chunk_index
            last = len(self._received) >= self._xfer_expected
            if self.sc.fail_at_chunk == k:
                self._note("fail", f"device lost at chunk {k}")
                if self.sc.fault_once:
                    self.sc.fail_at_chunk = None
                self._reenumerate("boot")
                return
            if self.sc.bad_ack_at_chunk == k:
                self._note("bad-ack", f"chunk {k}")
                if self.sc.fault_once:
                    self.sc.bad_ack_at_chunk = None
                self._reply(b"err_jcxx")
                self.mode = "boot"
                return
            if last:
                self._finish()
                return
            self._reply(b"ack_jcxx")

    def _finish(self):
        img = bytes(self._received)
        self.flashed = img
        if img[:4] == b"JCID":
            self.product = img[0x20:0x30].rstrip(b"\xff").split(b"_")[-1]
            v = img[0x40:0x44]
            self.version = img[0x47:0x4B] if v == b"vers" else v
        self._note("flashed", f"{self.product!r} {self.version!r} ({len(img)} B)")
        if self.sc.ack_last_chunk:
            self._reply(b"ack_jcxx")
            time.sleep(0.02)
        self._reenumerate("boot" if self.sc.verify_comes_back_in_boot else "app")


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Simulated AiXun T3x station on a pseudo-terminal")
    ap.add_argument("--product", default="T3BS")
    ap.add_argument("--version", default="1.06", help="application firmware version")
    ap.add_argument("--bootloader", action="store_true", help="start in bootloader (recovery) mode")
    ap.add_argument("--fail-at-chunk", type=int, help="drop off USB at this chunk (first transfer only)")
    ap.add_argument("--bad-ack-at-chunk", type=int, help="answer this chunk with a bad ACK (first transfer only)")
    ap.add_argument("--fault-every-time", action="store_true", help="repeat the injected fault on every transfer")
    ap.add_argument("--reenum-delay", type=float, default=1.0)
    ap.add_argument("--split-replies", action="store_true")
    ap.add_argument("--ports-file", default="/tmp/t3x-sim-ports.json")
    a = ap.parse_args(argv)
    sc = Scenario(product=a.product.encode(), app_version=a.version.encode(),
                  bootloader_string=b"00160000JC_M_" + a.product.encode() + b"_version1.01",
                  start_in_bootloader=a.bootloader, fail_at_chunk=a.fail_at_chunk,
                  bad_ack_at_chunk=a.bad_ack_at_chunk, reenum_delay=a.reenum_delay,
                  split_replies=a.split_replies, fault_once=not a.fault_every_time)
    sim = SimStation(sc, ports_file=a.ports_file)
    sim.start()
    print(f"Simulated {a.product} v{a.version} on {sim.device}")
    print(f"In another terminal:  export T3X_SIM_PORTS={a.ports_file}")
    seen = 0
    try:
        while True:
            time.sleep(0.2)
            for e in sim.log[seen:]:
                print(f"  [sim] {e.kind:8} {e.detail}")
            seen = len(sim.log)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
        try:
            os.remove(a.ports_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()
