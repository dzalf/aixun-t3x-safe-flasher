# SPDX-License-Identifier: GPL-2.0-or-later
"""CRC-16/MODBUS (poly 0x8005 reflected = 0xA001, init 0xFFFF, no xor-out).

Pure Python, table driven. Equivalent to the original updater's
crcmod.mkCrcFun(0x18005, rev=True, initCrc=0xFFFF, xorOut=0x0000), which
removes the crcmod build dependency (it fails to build on some systems).
"""


def _make_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        table.append(c)
    return tuple(table)


_TABLE = _make_table()


def crc16_modbus(data: bytes, crc: int = 0xFFFF) -> int:
    t = _TABLE
    for b in data:
        crc = (crc >> 8) ^ t[(crc ^ b) & 0xFF]
    return crc
