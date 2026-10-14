# SPDX-License-Identifier: GPL-2.0-or-later
"""Equivalence with the scripts that were proven on hardware.

The simulator records every byte the host writes. The refactored engine must
put exactly the same bytes on the wire as tests/reference/t3xupdate_safe.py
(the script that flashed the real T3BS 1.06 -> 1.16), and the same queries as
tests/reference/t3x_probe.py.
"""
import sys
import termios
import types

import pytest
import serial

from conftest import load_reference, make_image
from t3x.cli import probe as cli_probe
from t3x.core import image as fw
from t3x.core.flasher import Flasher
from t3x.core.link import SerialLink, Timing
from t3x.sim import Scenario, SimStation

QUERIES = {b"JC_identity", b"JC_version"}


class _OracleSerial(serial.Serial):
    """pyserial's flush() raises termios.error (EIO), not SerialException, when the device
    has just vanished. The frozen reference script catches only SerialException, so at the
    planned USB drop after the last chunk it crashes if the host loses that race (seen on
    the Pi in sessions 01 and 02; limitation L8). This shim converts the error to the
    exception the script already expects. It changes no byte on the wire: it only decides
    whether the oracle survives the drop that ends every flash."""

    def flush(self):
        try:
            super().flush()
        except (termios.error, OSError) as e:
            raise serial.SerialException(f"device lost during flush: {e}") from e


def _oracle_serial():
    shim = types.ModuleType("serial")
    shim.__dict__.update(serial.__dict__)
    shim.Serial = _OracleSerial
    return shim


def _ref_flash(monkeypatch, tmp_path, path):
    ref = load_reference("t3xupdate_safe.py")
    monkeypatch.setattr(ref, "serial", _oracle_serial())   # only the oracle sees the shim
    monkeypatch.chdir(tmp_path)
    with SimStation(Scenario()) as sim:
        monkeypatch.setattr(ref, "list_ports", types.SimpleNamespace(comports=sim.port_lister))
        args = types.SimpleNamespace(file=path, port=None, wait=20, yes=True, debug=False)
        ok = ref.do_update(args)
    return ok, sim


def _new_flash(path):
    img = fw.load(path)
    with SimStation(Scenario()) as sim:
        link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=20)
        r = Flasher(img, link).run()
    return r.ok, sim


@pytest.mark.slow
def test_flash_bytes_identical_to_hardware_proven_script(monkeypatch, tmp_path):
    path = tmp_path / "JC_M_T3BS_1.16.bin"
    path.write_bytes(make_image())                  # 166,144 B, 82 chunks like the real file
    ok_ref, sim_ref = _ref_flash(monkeypatch, tmp_path, str(path))
    ok_new, sim_new = _new_flash(str(path))
    assert ok_ref and ok_new
    assert sim_new.frames == sim_ref.frames
    assert bytes(sim_new.rx_stream) == bytes(sim_ref.rx_stream)
    assert sim_new.flashed == sim_ref.flashed == path.read_bytes()


@pytest.mark.slow
def test_state_changing_bytes_identical_to_upstream(monkeypatch, tmp_path):
    """Upstream t3xupdate.py sends extra read-only queries; everything else must match."""
    path = tmp_path / "JC_M_T3BS_1.16.bin"
    path.write_bytes(make_image())
    up = load_reference("t3xupdate_upstream.py")
    with SimStation(Scenario()) as sim_up:
        monkeypatch.setattr(up, "list_ports", types.SimpleNamespace(comports=sim_up.port_lister))
        assert up.T3XUpdater().do_update(str(path))
    _, sim_new = _new_flash(str(path))
    strip = lambda frames: [f for f in frames if f not in QUERIES]   # noqa: E731
    assert strip(sim_new.frames) == strip(sim_up.frames)
    assert sim_new.flashed == sim_up.flashed


def test_probe_queries_identical_to_reference(monkeypatch, tmp_path):
    ports_file = str(tmp_path / "ports.json")
    ref = load_reference("t3x_probe.py")
    with SimStation(Scenario(), ports_file=ports_file) as sim_ref:
        monkeypatch.setattr(ref, "list_ports", types.SimpleNamespace(comports=sim_ref.port_lister))
        monkeypatch.setattr(sys, "argv", ["t3x_probe.py", "--reader-test", "5"])
        with pytest.raises(SystemExit) as e:
            ref.main()
        assert e.value.code == 0
    monkeypatch.setenv("T3X_SIM_PORTS", ports_file)
    with SimStation(Scenario(), ports_file=ports_file) as sim_new:
        with pytest.raises(SystemExit) as e:
            cli_probe.main(["--reader-test", "5"])
        assert e.value.code == 0
    assert sim_new.frames == sim_ref.frames and set(sim_new.frames) == QUERIES
