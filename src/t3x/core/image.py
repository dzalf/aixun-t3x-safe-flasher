# SPDX-License-Identifier: GPL-2.0-or-later
"""AiXun update-file ("JCID") parsing and validation. No device I/O.

File layout (offsets in the file):
    0x00  b"JCID" magic
    0x20  product string, e.g. b"JC_M_T3BS", padded with 0xFF
    0x40  version, e.g. b"1.16"  (some T3A images: b"version1.26")
    0x60  payload size, big-endian  (file size = value + 0x100)
    0x64  CRC-16/MODBUS of the payload, big-endian
    0x100 plaintext Cortex-M image linked at 0x08010000
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .crc import crc16_modbus

MAGIC = b"JCID"
HEADER_SIZE = 0x100
CHUNK = 2048

APP_BASE = 0x08010000                      # main firmware start, per aixun_t3a_rev
APP_MAX = 0x2E800                          # bootloader size limit documented for T3A
SRAM_LO, SRAM_HI = 0x20000000, 0x20018000  # GD32F303 (48 KB) .. GD32F305/307 (96 KB)


class ImageError(Exception):
    """The file is not a usable update image."""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class FirmwareImage:
    path: Optional[str]
    data: bytes
    header_name: bytes = b""
    product: bytes = b""
    version: bytes = b""
    declared_size: int = 0
    crc_file: int = 0
    crc_calc: int = 0
    stack_pointer: int = 0
    reset_handler: int = 0
    checks: List[Check] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def payload_size(self) -> int:
        return max(0, len(self.data) - HEADER_SIZE)

    @property
    def n_chunks(self) -> int:
        return (len(self.data) + CHUNK - 1) // CHUNK

    @property
    def valid(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def product_str(self) -> str:
        return self.product.decode(errors="replace")

    @property
    def version_str(self) -> str:
        return self.version.decode(errors="replace")

    def chunks(self):
        """Yield (index, offset, data) exactly as the updater sends them."""
        for i, off in enumerate(range(0, len(self.data), CHUNK)):
            yield i, off, self.data[off:off + CHUNK]

    def vector_text(self) -> str:
        """Same wording as the original scripts' vector_check()."""
        ok_size = self.payload_size <= APP_MAX
        ok_sp = SRAM_LO < self.stack_pointer <= SRAM_HI
        ok_rst = self._reset_ok()
        return (f"payload {self.payload_size} B (limit {APP_MAX}) {'OK' if ok_size else 'TOO BIG'}; "
                f"SP 0x{self.stack_pointer:08X} {'OK' if ok_sp else 'BAD'}; "
                f"Reset 0x{self.reset_handler:08X} {'OK' if ok_rst else 'BAD'}")

    def _reset_ok(self) -> bool:
        r = self.reset_handler
        return (r & 1) == 1 and APP_BASE <= (r & ~1) < APP_BASE + self.payload_size

    def check(self, name: str) -> Optional[Check]:
        return next((c for c in self.checks if c.name == name), None)


# ----------------------------------------------------------------------
def parse_bytes(data: bytes, path: Optional[str] = None) -> FirmwareImage:
    """Parse and validate. Never raises for a bad image: inspect .checks/.valid."""
    img = FirmwareImage(path=path, data=bytes(data))
    checks = img.checks

    magic_ok = data[:4] == MAGIC
    checks.append(Check("magic", magic_ok, "JCID (update file)" if magic_ok else f"got {data[:4]!r}"))
    if not magic_ok or len(data) < HEADER_SIZE + 8:
        if magic_ok:
            checks.append(Check("size", False, f"file too small ({len(data)} B)"))
        return img

    img.declared_size = int.from_bytes(data[0x60:0x64], "big") + HEADER_SIZE
    size_ok = img.declared_size == len(data)
    checks.append(Check("size", size_ok, f"declared {img.declared_size} B, file {len(data)} B"))

    img.crc_file = int.from_bytes(data[0x64:0x66], "big")
    img.crc_calc = crc16_modbus(data[HEADER_SIZE:])
    checks.append(Check("crc", img.crc_file == img.crc_calc,
                        f"file {img.crc_file:04X}, calc {img.crc_calc:04X}"))

    img.header_name = data[0x20:0x30].rstrip(b"\xff")
    img.product = img.header_name.split(b"_")[-1]
    version = data[0x40:0x44]
    if version == b"vers":
        version = data[0x47:0x4B]
    img.version = version

    img.stack_pointer, img.reset_handler = struct.unpack("<II", data[0x100:0x108])
    vt_ok = (img.payload_size <= APP_MAX and SRAM_LO < img.stack_pointer <= SRAM_HI
             and img._reset_ok())
    checks.append(Check("vectors", vt_ok, img.vector_text()))
    return img


def load(path: str) -> FirmwareImage:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ImageError(str(e)) from e
    return parse_bytes(data, path)


def require_valid(img: FirmwareImage) -> FirmwareImage:
    """Raise ImageError with the same messages as t3xupdate_safe.py."""
    m = img.check("magic")
    if not m or not m.ok:
        raise ImageError("not an update file (no JCID magic).")
    s = img.check("size")
    if not s or not s.ok:
        raise ImageError(f"size mismatch, header {img.declared_size} vs file {img.size}.")
    c = img.check("crc")
    if not c.ok:
        raise ImageError(f"CRC mismatch, header {img.crc_file:04X} vs calc {img.crc_calc:04X}.")
    v = img.check("vectors")
    if not v.ok:
        raise ImageError("image does not look like a main-firmware image for this flash layout.")
    return img


# ----------------------------------------------------------------------
_VER_RE = re.compile(rb"(\d+)\.(\d+)")


def version_key(v: bytes):
    """Sortable key for b"1.16" style versions; unknown formats sort first."""
    m = _VER_RE.search(v or b"")
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def scan_directory(directory: str) -> List[FirmwareImage]:
    """Parse every *.bin in a directory (non-recursive), newest version first."""
    out = []
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".bin"):
            p = os.path.join(directory, name)
            if os.path.isfile(p):
                try:
                    out.append(load(p))
                except ImageError:
                    pass
    out.sort(key=lambda i: (i.product, version_key(i.version)), reverse=True)
    return out


@dataclass
class ImageDiff:
    same_size: bool
    differing_bytes: int
    compared_bytes: int
    only_in_a: List[str]
    only_in_b: List[str]

    @property
    def differing_pct(self) -> float:
        return 100.0 * self.differing_bytes / self.compared_bytes if self.compared_bytes else 0.0


def _strings(data: bytes, minlen: int = 5):
    return {m.group().decode().strip() for m in re.finditer(rb"[ -~]{%d,}" % minlen, data)}


def diff_images(a: FirmwareImage, b: FirmwareImage, interesting=re.compile(r"JC_|T3|C1|C2|T1")) -> ImageDiff:
    """Byte and string level comparison of two payloads (as done for T3B vs T3BS)."""
    pa, pb = a.data[HEADER_SIZE:], b.data[HEADER_SIZE:]
    n = min(len(pa), len(pb))
    diff = sum(1 for i in range(n) if pa[i] != pb[i]) + abs(len(pa) - len(pb))
    sa, sb = _strings(pa), _strings(pb)
    pick = lambda s: sorted(x for x in s if interesting.search(x))
    return ImageDiff(len(pa) == len(pb), diff, max(len(pa), len(pb)), pick(sa - sb), pick(sb - sa))
