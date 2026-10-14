# SPDX-License-Identifier: GPL-2.0-or-later
"""AiXun T3x serial protocol constants and reply parsing (115200 8N1).

    host -> station                      station -> host
    JC_identity                          JC_User (application) / JC_boot (bootloader)
    JC_version                           JC_M_T3BS_version1.06  (bootloader: 00160000JC_M_T3BS_version1.01)
    <version string echoed back>         JC_reset (optional), then USB drop -> bootloader
    0x%08x<bootloader string[8:]>        update_jcxx
    2048-byte chunks of the whole file   ack_jcxx per chunk; drop after the last one
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

BAUDRATE = 115200

CMD_IDENTITY = b"JC_identity"
CMD_VERSION = b"JC_version"
CMD_HARDWARE = b"JC_hardware"          # unverified, believed read-only (opt-in only)

ID_APP = b"JC_User"
ID_BOOT = b"JC_boot"
ACK_RESET = b"JC_reset"
ACK_START = b"update_jcxx"
ACK_CHUNK = b"ack_jcxx"

SERIAL_PREFIXES = ("JCID_T3", "AIXUN_T320", "JCID_T420D")
FTDI_IDS = (0x0403, 0x6001)

# Queries that cannot change station state. The probe refuses anything else.
READ_ONLY_COMMANDS = (CMD_IDENTITY, CMD_VERSION)


@dataclass
class VersionInfo:
    raw: bytes
    product: Optional[bytes]      # e.g. b"T3BS"
    version: Optional[bytes]      # last 4 bytes, e.g. b"1.06"
    bootloader_prefix: Optional[bytes] = None   # e.g. b"00160000" in bootloader replies

    @property
    def product_str(self) -> str:
        return self.product.decode(errors="replace") if self.product else "?"

    @property
    def version_str(self) -> str:
        return self.version.decode(errors="replace") if self.version else "?"


def parse_version(raw: bytes) -> VersionInfo:
    """Mirror the original parsing: product = split('_')[2], version = last 4 bytes.

    Works for both the application reply (JC_M_T3BS_version1.06) and the
    bootloader reply (00160000JC_M_T3BS_version1.01): in the latter the first
    '_' field is '00160000JC', so field 2 is still the product.
    """
    clean = raw.rstrip(b"\x00")
    parts = clean.split(b"_")
    product = parts[2] if len(parts) > 2 else None
    version = clean[-4:] if len(clean) >= 4 else None
    prefix = None
    if len(clean) > 8 and clean[:8].isdigit():
        prefix = clean[:8]
    return VersionInfo(clean, product, version, prefix)


def start_command(image_size: int, bootloader_raw: bytes) -> bytes:
    """Transfer start string, byte-identical to the original updater."""
    return f"0x{image_size:08x}{bootloader_raw[8:].decode()}".encode()


def mode_name(identity: bytes) -> str:
    return {ID_APP: "application", ID_BOOT: "bootloader"}.get(identity, "unknown")
