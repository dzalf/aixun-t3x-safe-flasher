# SPDX-License-Identifier: GPL-2.0-or-later
"""GUI flows driven end-to-end against the simulated station (offscreen, no display needed)."""
import json
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import make_image  # noqa: E402
from t3x.core import events as ev  # noqa: E402
from t3x.core.link import SerialLink, Timing  # noqa: E402
from t3x.gui import theme  # noqa: E402
from t3x.gui.window import MainWindow, Settings  # noqa: E402
from t3x.gui.widgets import ACKED, FAILED  # noqa: E402
from t3x.sim import Scenario, SimStation  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.QSS)
    return a


def wait_until(app, cond, timeout=30.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(step)
    app.processEvents()
    return cond()


@pytest.fixture
def fwdir(tmp_path):
    d = tmp_path / "firmware"
    d.mkdir()
    (d / "JC_M_T3BS_1.16.bin").write_bytes(make_image(payload=20 * 2048 + 256))
    (d / "JC_M_T3BS_1.06.bin").write_bytes(make_image(version=b"1.06", payload=20 * 2048 + 256, seed=3))
    (d / "JC_M_T3B_1.16.bin").write_bytes(make_image(product=b"T3B", payload=20 * 2048 + 256, seed=4))
    return str(d)


def make_window(app, sim, fwdir, tmp_path, **kw):
    s = Settings(firmware_dir=fwdir, results_dir=str(tmp_path / "results"), port_lister=sim.port_lister,
                 link_factory=lambda emit: SerialLink(None, 5, emit=emit, port_lister=sim.port_lister,
                                                      timing=Timing.fast()),
                 poll_ms=100, reader_test=3, wait=5, **{"simulated": True, **kw})
    w = MainWindow(s)
    w.confirm_dialog = lambda *_: True
    w.warned = []
    w.warn_dialog = lambda t, m: w.warned.append(t)
    w.show()
    return w


def probe_done(w):
    return w.report is not None and not w.busy and not w.probing


def test_full_flash_flow(app, fwdir, tmp_path):
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: probe_done(w)), "auto-probe did not finish"
        cp = w.connect_page
        assert cp.badge.text() == "T3BS" and cp.next_btn.isEnabled()
        assert "T3B" in cp.note.label.text()               # sticker/USB name vs firmware line note
        cp.next_btn.click()
        vp = w.verify_page
        assert w.stack.currentWidget() is vp
        assert w.image and w.image.version == b"1.16" and w.image.product == b"T3BS"   # best match chosen
        assert vp.all_ok and not vp.flash_btn.isEnabled()  # checkbox not ticked yet
        assert "1.15" in vp.changes_lbl.text()             # changelog since 1.06
        assert "Rollback image: JC_M_T3BS_1.06.bin" in vp.banner.label.text()
        vp.confirm.setChecked(True)
        assert vp.flash_btn.isEnabled()
        vp.flash_btn.click()
        assert w.flashing and w.stack.currentWidget() is w.flash_page
        w.close()                                          # must be refused mid-transfer
        assert w.isVisible() and w.warned == ["Update in progress"]
        assert wait_until(app, lambda: not w.flashing, 60)
        assert w.stack.currentWidget() is w.done_page
        assert w.last_result.ok and sim.version == b"1.16"
        assert w.done_page.title.text() == "Update successful"
        assert all(st == ACKED for st in w.done_page.map.state)
        assert os.path.exists(w.last_log) and "Update successful" in open(w.last_log).read()
        rep = json.load(open(w.write_report(str(tmp_path / "r.json"))))
        assert rep["result"]["ok"] and rep["result"]["after"] == "JC_M_T3BS_version1.16"
        lines = "\n".join(w.flash_page.log.lines)
        assert "Entering bootloader" in lines and "ack_jcxx" in lines
        w.close()


def test_mismatched_image_cannot_be_flashed(app, fwdir, tmp_path):
    with SimStation(Scenario()) as sim:
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        vp = w.verify_page
        t3b_row = next(i for i, img in enumerate(vp.images) if img.product == b"T3B")
        vp.lib.selectRow(t3b_row)
        vp.confirm.setChecked(True)
        assert not vp.all_ok and not vp.flash_btn.isEnabled()
        assert "product mismatch" in vp.lib.item(t3b_row, 3).text()
        w.start_flash()                       # even calling it directly must not reach the station...
        assert wait_until(app, lambda: not w.busy, 10)
        # ...the button gate is the UI rule; the engine's product check is the backstop
        assert sim.version == b"1.06"
        w.close()


def test_station_changed_after_verify_writes_nothing(app, fwdir, tmp_path):
    with SimStation(Scenario()) as sim:
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        sim.version = b"1.07"                 # someone updated the station in between
        w.verify_page.confirm.setChecked(True)
        w.verify_page.flash_btn.click()
        assert wait_until(app, lambda: not w.flashing, 20)
        r = w.last_result
        assert r.stage == ev.Stage.ABORTED and not r.wrote_anything
        assert set(sim.frames) <= {b"JC_identity", b"JC_version"}
        assert w.done_page.title.text() == "Update cancelled"
        w.close()


def test_interrupted_then_recovery_page(app, fwdir, tmp_path):
    with SimStation(Scenario(fail_at_chunk=6, reenum_delay=0.05)) as sim:
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        w.verify_page.confirm.setChecked(True)
        w.verify_page.flash_btn.click()
        assert wait_until(app, lambda: not w.flashing, 30)
        dp = w.done_page
        assert dp.title.text() == "Update not completed" and dp.retry.isVisible()
        assert FAILED in dp.map.state and dp.map.state.count(ACKED) == 5
        assert "Do NOT power off" in " ".join(
            dp.next_lay.itemAt(i).widget().text() for i in range(dp.next_lay.count()))
        sim.sc.fail_at_chunk = None
        dp.retry.click()                       # re-probe: station is now in its bootloader
        assert wait_until(app, lambda: probe_done(w) and w.stack.currentWidget() is w.recovery_page, 20)
        rp = w.recovery_page
        assert "stopped at chunk 6/21" in rp.last.label.text()
        assert rp.go.isEnabled() and "T3BS 1.16" in rp.go.text()
        rp.go.click()                          # confirm_dialog -> True
        assert wait_until(app, lambda: not w.flashing and w.last_result is not None
                          and w.stack.currentWidget() is w.done_page, 40)
        assert w.last_result.ok and sim.version == b"1.16"
        w.close()


def test_unplug_returns_to_connect(app, fwdir, tmp_path):
    with SimStation(Scenario()) as sim:
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        sim._detach()                          # cable pulled while idle on the Verify page
        assert wait_until(app, lambda: w.stack.currentWidget() is w.connect_page and w.report is None, 5)
        assert "disconnected" in w.connect_page.line2.text()
        w.close()


def test_no_firmware_folder_explains(app, tmp_path):
    with SimStation(Scenario()) as sim:
        w = make_window(app, sim, str(tmp_path / "missing"), tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        assert "No firmware images" in w.verify_page.banner.label.text()
        assert not w.verify_page.flash_btn.isEnabled()
        w.close()


def test_station_plugged_in_after_start(app, fwdir, tmp_path):
    """Session 02b: GUI started first, station plugged in later and silent for its first
    seconds on USB. The GUI must stay usable and find the station by itself."""
    sim = SimStation(Scenario())
    sim.start(attached=False)
    try:
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: "No AiXun station" in w.connect_page.line2.text(), 5)
        t0 = time.monotonic()
        sim.plug(wake_delay=4.0)
        # while the station is still silent, Rescan and the port list stay usable
        assert wait_until(app, lambda: w.probing, 6)
        assert w.rescan.isEnabled() and w.port_combo.isEnabled()
        assert wait_until(app, lambda: probe_done(w), 30)
        took = time.monotonic() - t0
        assert w.report.identity == b"JC_User" and w.connect_page.next_btn.isEnabled()
        assert took < 15, f"found after {took:.1f} s"
        w.close()
    finally:
        sim.stop()


def test_rescan_cancels_a_running_probe(app, fwdir, tmp_path):
    sim = SimStation(Scenario())
    sim.start(attached=False)
    try:
        w = make_window(app, sim, fwdir, tmp_path)
        sim.plug(wake_delay=60)                       # never answers during this test
        assert wait_until(app, lambda: w.probing, 6)
        t0 = time.monotonic()
        w.rescan.click()                              # user gives up waiting
        assert wait_until(app, lambda: w._cancelled_count >= 1, 5)
        assert time.monotonic() - t0 < 2, "cancel must not wait for the probe's timeouts"
        w.close()
    finally:
        sim.stop()


def test_port_busy_right_after_plugging_is_retried(app, fwdir, tmp_path, monkeypatch):
    """Another program (e.g. ModemManager) can hold a new serial port for a few seconds:
    opening it fails with EBUSY. The GUI keeps retrying instead of giving up."""
    import serial
    from t3x.core import probe as probe_mod
    real, calls = serial.Serial, []

    def busy_then_ok(*a, **kw):
        calls.append(a)
        if len(calls) <= 2:
            raise serial.SerialException("[Errno 16] could not open port: Device or resource busy")
        return real(*a, **kw)

    monkeypatch.setattr(probe_mod.serial, "Serial", busy_then_ok)
    sim = SimStation(Scenario())
    sim.start(attached=False)
    try:
        w = make_window(app, sim, fwdir, tmp_path)
        sim.plug()
        assert wait_until(app, lambda: "busy" in w.connect_page.line2.text(), 10)
        assert wait_until(app, lambda: probe_done(w), 20)
        assert w.report.identity == b"JC_User" and len(calls) == 3
        w.close()
    finally:
        sim.stop()


def test_unplug_during_probe_then_replug(app, fwdir, tmp_path):
    sim = SimStation(Scenario())
    sim.start(attached=False)
    try:
        w = make_window(app, sim, fwdir, tmp_path)
        sim.plug(wake_delay=60)
        assert wait_until(app, lambda: w.probing, 6)
        sim.unplug()
        assert wait_until(app, lambda: not w.probing and "No AiXun station" in w.connect_page.line2.text(), 8)
        sim.plug(wake_delay=0)
        assert wait_until(app, lambda: probe_done(w), 15)
        assert w.report.identity == b"JC_User"
        w.close()
    finally:
        sim.stop()


def test_manually_added_files_are_checked_and_confirmation_resets(app, fwdir, tmp_path, monkeypatch):
    """Session 02c: 'Add file…' images get the same checks as library images; switching to
    another file clears the confirmation tick; downgrades are flagged."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    other = tmp_path / "elsewhere"
    other.mkdir()
    good = other / "JC_M_T3BS_1.05.bin"
    good.write_bytes(make_image(version=b"1.05", payload=20 * 2048 + 256, seed=9))
    t3b = other / "JC_M_T3B_1.15.bin"
    t3b.write_bytes(make_image(product=b"T3B", version=b"1.15", payload=20 * 2048 + 256, seed=8))
    bad = bytearray(make_image(version=b"1.15", payload=20 * 2048 + 256, seed=7))
    bad[-1] ^= 0xFF
    crc = other / "corrupt.bin"
    crc.write_bytes(bytes(bad))
    junk = other / "junk.bin"
    junk.write_bytes(b"hello")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    with SimStation(Scenario()) as sim:                  # station reports T3BS 1.06
        w = make_window(app, sim, fwdir, tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        vp = w.verify_page

        def add(f):
            monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(f), ""))
            vp.choose_file()
            app.processEvents()
            return [vp.checks.item(r, 0).text() for r in range(vp.checks.rowCount())
                    if vp.checks.item(r, 2).text() != "PASS"]

        vp.confirm.setChecked(True)                      # ticked for the library's 1.16 …
        assert vp.flash_btn.isEnabled()
        assert add(good) == []                           # … then a valid file is added and selected
        assert not vp.confirm.isChecked() and not vp.flash_btn.isEnabled()   # tick did not carry over
        assert good.name in vp.checking.text() and "SHA-256" in vp.checking.text()
        assert "DOWNGRADE 1.06 → 1.05" in vp.banner.label.text()
        vp.confirm.setChecked(True)
        assert vp.flash_btn.isEnabled()
        assert add(t3b) == ["Product match"] and not vp.flash_btn.isEnabled()
        assert add(crc) == ["CRC16"] and not vp.flash_btn.isEnabled()
        assert "Image header (JCID)" in add(junk) and not vp.flash_btn.isEnabled()
        w.close()
