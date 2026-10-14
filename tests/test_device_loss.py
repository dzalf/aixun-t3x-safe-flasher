# SPDX-License-Identifier: GPL-2.0-or-later
"""Device loss surfacing as termios.error (EIO) instead of SerialException.

Found on the Raspberry Pi 5 (Python 3.14, session 01a): when the station drops
off USB right after a write, pyserial's flush() -> tcdrain() raises
termios.error(5, 'Input/output error'), which is not a SerialException. The
reference script t3xupdate_safe.py has the same latent issue; it did not
trigger on the 2026-10-08 hardware run, but timing could make it do so at the
two moments the station resets on purpose: the bootloader echo and the last
chunk. These tests force the error deterministically at exactly those points.
"""
import termios

import pytest
import serial

from conftest import make_image
from t3x.cli import probe as cli_probe
from t3x.core import image as fw
from t3x.core.flasher import Flasher
from t3x.core.link import DeviceLost, SerialLink, Timing
from t3x.sim import Scenario, SimStation


@pytest.fixture
def flush_fails_after(monkeypatch):
    """flush() raises EIO right after writing data matching `predicate`."""
    def install(predicate):
        real_write, real_flush = serial.Serial.write, serial.Serial.flush

        def write(self, data):
            self._t3x_last = bytes(data)
            return real_write(self, data)

        def flush(self):
            if predicate(getattr(self, "_t3x_last", b"")):
                self._t3x_last = b""
                raise termios.error(5, "Input/output error")
            return real_flush(self)

        monkeypatch.setattr(serial.Serial, "write", write)
        monkeypatch.setattr(serial.Serial, "flush", flush)
    return install


def run_flash(sim, img):
    link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=5)
    return Flasher(img, link).run()


IMG = fw.parse_bytes(make_image(payload=20 * 2048 + 256))
LAST = list(IMG.chunks())[-1][2]


def test_transfer_converts_eio_to_device_lost(flush_fails_after):
    flush_fails_after(lambda d: d == b"JC_identity")
    with SimStation(Scenario()) as sim:
        link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=2)
        link.connect()
        with pytest.raises(DeviceLost):
            link.transfer(b"JC_identity")
        link.close()


def test_eio_after_last_chunk_is_the_expected_drop(flush_fails_after):
    """The exact failure seen on the Pi: must now finish as a successful update."""
    flush_fails_after(lambda d: d == LAST)
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        r = run_flash(sim, IMG)
    assert r.ok and sim.version == b"1.16"


def test_eio_on_bootloader_echo_is_the_expected_drop(flush_fails_after):
    flush_fails_after(lambda d: d == b"JC_M_T3BS_version1.06")
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        r = run_flash(sim, IMG)
    assert r.ok


def test_eio_mid_transfer_is_reported_not_raised(flush_fails_after):
    chunk5 = list(IMG.chunks())[4][2]
    flush_fails_after(lambda d: d == chunk5)
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        r = run_flash(sim, IMG)
    assert not r.ok and "Device lost at chunk 5/21" in r.message and "do NOT power off" in r.message


def test_probe_cli_reports_disconnect_cleanly(flush_fails_after, tmp_path, monkeypatch, capsys):
    ports = str(tmp_path / "ports.json")
    monkeypatch.setenv("T3X_SIM_PORTS", ports)
    flush_fails_after(lambda d: d == b"JC_version")
    with SimStation(Scenario(), ports_file=ports):
        with pytest.raises(SystemExit) as e:
            cli_probe.main(["--repeat", "1"])
    out = capsys.readouterr().out
    assert e.value.code == 1 and "station disconnected during the probe" in out
