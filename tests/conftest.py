# SPDX-License-Identifier: GPL-2.0-or-later
import importlib.util
import logging
import os
import random
import struct
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from t3x.core.crc import crc16_modbus  # noqa: E402

# The reference scripts import crcmod; provide an equivalent if it is not installed.
if importlib.util.find_spec("crcmod") is None:
    fake = types.ModuleType("crcmod")

    def mkCrcFun(poly, rev=True, initCrc=0xFFFF, xorOut=0):
        assert (poly, rev, initCrc, xorOut) == (0x18005, True, 0xFFFF, 0)
        return crc16_modbus

    fake.mkCrcFun = mkCrcFun
    sys.modules["crcmod"] = fake


def make_image(product=b"T3BS", version=b"1.16", payload=165888, seed=1,
               sp=0x20005508, reset=0x08010165, legacy_version=False) -> bytes:
    """Synthetic but structurally valid JCID update image (no vendor code)."""
    rnd = random.Random(seed)
    body = bytearray(rnd.getrandbits(8) for _ in range(payload))
    body[0:8] = struct.pack("<II", sp, reset)
    hdr = bytearray(b"\xff" * 0x100)
    hdr[0:4] = b"JCID"
    name = b"JC_M_" + product
    hdr[0x20:0x20 + len(name)] = name
    if legacy_version:
        v = b"version" + version
        hdr[0x40:0x40 + len(v)] = v
    else:
        hdr[0x40:0x44] = version
    hdr[0x60:0x64] = payload.to_bytes(4, "big")
    hdr[0x64:0x66] = crc16_modbus(bytes(body)).to_bytes(2, "big")
    return bytes(hdr) + bytes(body)


@pytest.fixture(autouse=True)
def _restore_t3x_logger():
    """The reference script adds handlers to the shared 't3x' logger, one of them on the
    stderr that pytest captures for that test only. Left in place, later tests log into a
    closed stream ("--- Logging error --- ValueError: I/O operation on closed file")."""
    log = logging.getLogger("t3x")
    before, level = list(log.handlers), log.level
    yield
    for h in log.handlers:
        if h not in before:
            log.removeHandler(h)
            h.close()
    log.setLevel(level)


@pytest.fixture
def image_file(tmp_path):
    def _make(name="JC_M_T3BS_1.16.bin", **kw):
        p = tmp_path / name
        p.write_bytes(make_image(**kw))
        return str(p)
    return _make


def load_reference(name):
    """Import a script from tests/reference as a module."""
    path = os.path.join(ROOT, "tests", "reference", name)
    spec = importlib.util.spec_from_file_location("ref_" + name.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REAL_FW_DIR = os.environ.get("T3X_FW_DIR")


def real_fw(name):
    if not REAL_FW_DIR or not os.path.exists(os.path.join(REAL_FW_DIR, name)):
        pytest.skip(f"set T3X_FW_DIR to a folder containing {name}")
    return os.path.join(REAL_FW_DIR, name)
