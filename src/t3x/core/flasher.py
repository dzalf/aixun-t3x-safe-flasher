# SPDX-License-Identifier: GPL-2.0-or-later
"""The update procedure as a UI-free engine.

Ported from t3xupdate_safe.py: the sequence of bytes on the wire is identical
(tests/test_golden.py compares the full transcript). Differences are limited
to error paths and safety:

* Device loss during pre-flight, start or verify is reported instead of
  crashing with a traceback.
* In bootloader (recovery) mode the product is also checked, using the
  product field of the bootloader's own version string
  (e.g. 00160000JC_M_T3BS_version1.01 -> T3BS). The original skipped this
  check whenever the station was not in application mode. No extra bytes are
  sent: the string is the reply to the first JC_version query.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import events as ev
from .events import Stage
from .image import FirmwareImage, ImageError, require_valid
from .link import DeviceLost, LinkError, SerialLink
from .protocol import (ACK_CHUNK, ACK_RESET, ACK_START, ID_APP, ID_BOOT, VersionInfo, parse_version,
                       start_command)


@dataclass
class Preflight:
    port: str
    identity: bytes
    station: VersionInfo
    image: FirmwareImage

    @property
    def in_bootloader(self) -> bool:
        return self.identity == ID_BOOT

    @property
    def same_version(self) -> bool:
        return (not self.in_bootloader and self.station.version is not None
                and self.station.version == self.image.version)


@dataclass
class FlashResult:
    ok: bool
    stage: Stage
    message: str = ""
    fatal: bool = False                      # like the original's SystemExit paths
    chunks_acked: int = 0
    n_chunks: int = 0
    preflight: Optional[Preflight] = None
    bootloader: Optional[VersionInfo] = None
    after: Optional[VersionInfo] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    transfer_seconds: float = 0.0
    wrote_anything: bool = False             # True once update_jcxx was received

    @property
    def duration(self) -> float:
        return self.finished_at - self.started_at


Confirm = Callable[[Preflight], bool]


def always_yes(_p: Preflight) -> bool:
    return True


@dataclass
class Flasher:
    image: FirmwareImage
    link: SerialLink
    emit: ev.Emitter = ev.null_emit
    confirm: Confirm = always_yes
    allow_unknown_product: bool = False      # recovery only: bootloader string without product
    result: FlashResult = field(init=False)

    # ------------------------------------------------------------------
    def _stage(self, stage: Stage, detail: str = "") -> None:
        self.result.stage = stage
        self.emit(ev.StageEvent(stage, detail))

    def _fail(self, message: str, fatal: bool = False, stage: Stage = Stage.FAILED) -> FlashResult:
        if self._t_transfer is not None and not self.result.transfer_seconds:
            self.result.transfer_seconds = time.monotonic() - self._t_transfer
        if not fatal:
            ev.error(self.emit, message)
        self.result.ok = False
        self.result.message = message
        self.result.fatal = fatal
        self.result.finished_at = time.time()
        self._stage(stage, message)
        return self.result

    # ------------------------------------------------------------------
    def run(self) -> FlashResult:
        self.result = FlashResult(False, Stage.LOAD, n_chunks=self.image.n_chunks, started_at=time.time())
        self._t_transfer = None
        try:
            return self._run()
        except LinkError as e:
            return self._fail(str(e), fatal=True)
        finally:
            self.link.close()

    def _load(self) -> bool:
        img = self.image
        self._stage(Stage.LOAD)
        try:
            for name in ("magic", "size", "crc"):
                c = img.check(name)
                if not c or not c.ok:
                    require_valid(img)          # raises with the original wording
            ev.info(self.emit, f"Vector table: {img.vector_text()}")
            require_valid(img)
        except ImageError as e:
            self._fail(str(e), fatal=True)
            return False
        ev.info(self.emit, f"Update file: {img.product_str} v{img.version_str} "
                           f"({img.size} bytes, CRC {img.crc_calc:04X} OK)")
        return True

    def _run(self) -> FlashResult:
        img, link, emit = self.image, self.link, self.emit
        if not self._load():
            return self.result

        # ---------------------------------------------------------- pre-flight
        self._stage(Stage.CONNECT)
        port = link.connect(tag="initial")
        self._stage(Stage.PREFLIGHT, port)
        try:
            raw = link.transfer(b"JC_version")
            ident = link.transfer(b"JC_identity")
        except DeviceLost:
            return self._fail("Station disconnected during pre-flight. Nothing was written.")
        station = parse_version(raw)
        ev.info(emit, f"Station: identity {ident!r}, version string {raw!r}")
        pf = Preflight(port, ident, station, img)
        self.result.preflight = pf

        product = station.product or b"?"
        if ident == ID_APP and product != img.product:
            return self._fail(f"Product mismatch: file {img.product!r} vs station {product!r}. Aborting.")
        if ident == ID_BOOT:
            if station.product is None and not self.allow_unknown_product:
                return self._fail(f"Bootloader string {raw!r} has no product field; refusing to flash "
                                  "without --allow-unknown-product.")
            if station.product is not None and station.product != img.product:
                return self._fail(f"Product mismatch: file {img.product!r} vs bootloader "
                                  f"{station.product!r}. Aborting.")

        self._stage(Stage.CONFIRM)
        if not self.confirm(pf):
            ev.info(emit, "Aborted by user. Nothing was written.")
            self.result.message = "Aborted by user. Nothing was written."
            self.result.finished_at = time.time()
            self._stage(Stage.ABORTED)
            return self.result

        # ---------------------------------------------------------- bootloader
        self._stage(Stage.BOOTLOADER)
        if not self._enter_bootloader():
            return self.result

        self._stage(Stage.START)
        try:
            bl_raw = link.transfer(b"JC_version")
            ev.info(emit, f"Bootloader version string: {bl_raw!r}")
            self.result.bootloader = parse_version(bl_raw)
            ack = link.transfer(start_command(img.size, bl_raw))
        except DeviceLost:
            return self._fail("Station disconnected before the transfer started. Nothing written yet; "
                              "re-run is safe.")
        if ack != ACK_START:
            return self._fail(f"No update start ACK (got {ack!r}). Nothing written yet; re-run is safe.")
        self.result.wrote_anything = True

        # ---------------------------------------------------------- transfer
        self._stage(Stage.TRANSFER)
        ev.info(emit, "Sending firmware...")
        n = img.n_chunks
        t0 = self._t_transfer = time.monotonic()
        for i, off, data in img.chunks():
            last = i == n - 1
            try:
                ack = link.transfer(data, timeout=link.t.chunk_timeout)
            except DeviceLost:
                if last:
                    ev.warning(emit, "Device dropped after last chunk (expected: station restarting).")
                    break
                return self._fail(f"Device lost at chunk {i + 1}/{n}. Station should be in "
                                  "bootloader: do NOT power off, re-run this script.")
            if ack != ACK_CHUNK:
                if last and ack == b"":
                    ev.warning(emit, "No ACK on last chunk; station may already be restarting.")
                    break
                return self._fail(f"Bad ACK at chunk {i + 1}/{n}: {ack!r}. Do NOT power off; re-run.")
            self.result.chunks_acked = i + 1
            emit(ev.ProgressEvent(i + 1, n, off + len(data), img.size))
        self.result.transfer_seconds = time.monotonic() - t0
        # the final chunk is normally answered by a USB drop instead of an ACK;
        # it was delivered, and the verify step below is what confirms it.
        if self.result.chunks_acked < n:
            self.result.chunks_acked = n
            emit(ev.ProgressEvent(n, n, img.size, img.size))

        # ---------------------------------------------------------- verify
        self._stage(Stage.VERIFY)
        time.sleep(link.t.after_flash)
        link.connect(allow_fallback=True, tag="after-flash")
        ident = None
        try:
            for _ in range(link.t.verify_tries):
                ident = link.transfer(b"JC_identity")
                if ident:
                    break
                time.sleep(link.t.verify_gap)
            raw = link.transfer(b"JC_version")
        except DeviceLost:
            return self._fail("Station disconnected while confirming the new version. "
                              "Do NOT power off; send the log.")
        after = parse_version(raw)
        self.result.after = after
        ev.info(emit, f"After flash: identity {ident!r}, version {raw!r}")
        if ident == ID_APP and raw.endswith(img.version):
            msg = f"Update successful. Station now runs {img.product_str} v{img.version_str}."
            ev.info(emit, msg)
            self.result.ok = True
            self.result.message = msg
            self.result.finished_at = time.time()
            self._stage(Stage.DONE, msg)
            return self.result
        return self._fail("Could not confirm the new version. Do NOT power off; send me the log.")

    def _enter_bootloader(self) -> bool:
        link, emit = self.link, self.emit
        try:
            ident = link.transfer(b"JC_identity")
        except DeviceLost:
            self._fail("Station disconnected before entering the bootloader. Nothing was written.")
            return False
        if ident == ID_BOOT:
            ev.info(emit, "Station already in bootloader.")
            return True
        if ident != ID_APP:
            self._fail(f"Unexpected identity {ident!r}")
            return False

        ev.info(emit, "Entering bootloader...")
        try:
            ack = link.transfer(link.transfer(b"JC_version"))
            if ack != ACK_RESET:
                ev.warning(emit, f"No JC_reset ACK (got {ack!r}); continuing as the original does.")
        except DeviceLost:
            ev.warning(emit, "Device dropped off USB (expected: station resetting into bootloader).")

        time.sleep(link.t.after_reset)
        link.connect(allow_fallback=True, tag="after-bootloader-entry")
        ident = b""
        for _ in range(link.t.boot_confirm_tries):
            try:
                ident = link.transfer(b"JC_identity")
            except DeviceLost:
                ident = b""
            if ident == ID_BOOT:
                return True
            time.sleep(link.t.boot_confirm_gap)
        self._fail(f"Could not confirm bootloader. Identity {ident!r}")
        return False
