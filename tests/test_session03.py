# SPDX-License-Identifier: GPL-2.0-or-later
"""Session 03: one-shot simulator faults, simulator logs kept apart, downgrade and
ModemManager notices, flash history."""
import json
import os

from conftest import make_image
from test_cli import run, sim_env  # noqa: F401  (fixture)
from t3x.cli import probe as cli_probe
from t3x.cli import update as cli_update
from t3x.core import environment, history
from t3x.core import image as fw
from t3x.core.flasher import Flasher
from t3x.core.link import SerialLink, Timing
from t3x.core.logfile import SIM_MARKER, is_simulated_log, latest_log
from t3x.sim import Scenario, SimStation


def _flash(sim, img):
    link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=5)
    return Flasher(img, link).run()


def test_injected_fault_happens_once_like_a_cable_pull():
    img = fw.parse_bytes(make_image(payload=20 * 2048 + 256))
    with SimStation(Scenario(fail_at_chunk=8, reenum_delay=0.05)) as sim:
        first = _flash(sim, img)
        second = _flash(sim, img)                 # nothing reset by hand: the "cable" is back in
    assert not first.ok and first.chunks_acked == 7
    assert second.ok and sim.version == b"1.16"


def test_fault_every_time_is_still_available():
    img = fw.parse_bytes(make_image(payload=20 * 2048 + 256))
    with SimStation(Scenario(fail_at_chunk=8, reenum_delay=0.05, fault_once=False)) as sim:
        assert not _flash(sim, img).ok
        assert not _flash(sim, img).ok


def test_latest_log_skips_simulator_logs(tmp_path):
    real = tmp_path / "t3x_flash_20261011_235102.log"
    real.write_text("23:51:02.579 DEBUG: [initial] /dev/ttyUSB0 0403:6001\n")
    legacy_sim = tmp_path / "t3x_flash_20261012_000100.log"          # before session 03: no marker
    legacy_sim.write_text("00:01:00.000 DEBUG: [initial] /tmp/t3x-sim-abc/ttyUSB0 0403:6001\n")
    new_sim = tmp_path / "t3x_flash_20261012_000200.log"
    new_sim.write_text(f"00:02:00.000 INFO: {SIM_MARKER}\n")
    assert is_simulated_log(str(legacy_sim)) and is_simulated_log(str(new_sim))
    assert not is_simulated_log(str(real))
    assert latest_log(str(tmp_path)) == str(real)
    assert latest_log(str(tmp_path), include_simulated=True) == str(new_sim)


def test_probe_cli_flags_downgrade(sim_env, image_file, capsys):  # noqa: F811
    with sim_env(app_version=b"1.16"):
        code = run(cli_probe.main, ["--fw", image_file(version=b"1.15"), "--repeat", "1"])
    out = capsys.readouterr().out
    assert code == 0 and "Station v1.16 vs file v1.15  (DOWNGRADE)" in out
    assert "check the station's settings and temperature" in out


def test_update_cli_flags_downgrade_and_modemmanager(sim_env, image_file, tmp_path, capsys,  # noqa: F811
                                                    monkeypatch):
    monkeypatch.setattr(environment, "simulated", lambda: False)      # behave as on real hardware
    monkeypatch.setenv("T3X_ASSUME_MODEMMANAGER", "1")
    monkeypatch.setattr("builtins.input", lambda _p: "no")            # stop at the prompt
    with sim_env(app_version=b"1.16") as sim:
        code = run(cli_update.main, [image_file(version=b"1.15", payload=4096), "--log-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1 and set(sim.frames) <= {b"JC_identity", b"JC_version"}
    assert "DOWNGRADE 1.16 -> 1.15" in out and "sudo systemctl stop ModemManager" in out
    rec = history.load(str(tmp_path))[-1]                            # a declined run is recorded too
    assert not rec["ok"] and not rec["wrote_anything"] and rec["stage"] == "ABORTED"


def test_history_is_robust_and_summarised(tmp_path):
    p = tmp_path / history.FILE_NAME
    good = {"time": "2026-10-11 23:51:02", "ok": True, "product": "T3BS", "version": "1.16",
            "before_version": "JC_M_T3BS_version1.15", "chunks_acked": 82, "n_chunks": 82, "transfer_s": 16.7}
    p.write_text("not json\n" + json.dumps(good) + "\n[1, 2]\n")
    recs = history.load(str(tmp_path))
    assert recs == [good]
    assert history.summary(good) == "2026-10-11 23:51:02  T3BS 1.15 → 1.16  OK  82/82  16.7 s"
    assert history.load(str(tmp_path / "missing")) == []


def test_modemmanager_check_is_read_only_and_overridable(monkeypatch):
    monkeypatch.setenv("T3X_ASSUME_MODEMMANAGER", "0")
    assert environment.modemmanager_active() is False
    monkeypatch.setenv("T3X_ASSUME_MODEMMANAGER", "1")
    assert environment.modemmanager_active() is True
    monkeypatch.delenv("T3X_ASSUME_MODEMMANAGER")
    monkeypatch.setenv("PATH", "/nonexistent")                        # no systemctl → unknown
    assert environment.modemmanager_active() is None


def test_gui_records_history_and_shows_it(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from test_gui import make_window, probe_done, wait_until
    from PySide6.QtWidgets import QApplication
    from t3x.gui import theme
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.QSS)
    fwdir = tmp_path / "firmware"
    fwdir.mkdir()
    (fwdir / "JC_M_T3BS_1.16.bin").write_bytes(make_image(payload=20 * 2048 + 256))
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        w = make_window(app, sim, str(fwdir), tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        w.verify_page.confirm.setChecked(True)
        w.verify_page.flash_btn.click()
        assert wait_until(app, lambda: not w.flashing and w.last_result is not None, 40)
        assert w.last_result.ok
        recs = history.load(w.s.results_dir)
        assert len(recs) == 1 and recs[0]["tool"] == "t3x-gui" and recs[0]["simulated"]
        w.show_history()
        t = w.history_dialog.table
        assert t.rowCount() == 1 and t.item(0, 3).text() == "✔ OK" and t.item(0, 2).text() == "1.16"
        assert "SHA-256" in t.item(0, 0).toolTip()
        w.history_dialog.close()
        w.close()


def test_gui_modemmanager_notice(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from test_gui import make_window, probe_done, wait_until
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("T3X_ASSUME_MODEMMANAGER", "1")
    fwdir = tmp_path / "firmware"
    fwdir.mkdir()
    (fwdir / "JC_M_T3BS_1.16.bin").write_bytes(make_image(payload=20 * 2048 + 256))
    with SimStation(Scenario()) as sim:
        w = make_window(app, sim, str(fwdir), tmp_path, simulated=False)   # as on real hardware
        assert w.mm_active
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        assert "ModemManager is running" in w.verify_page.banner.label.text()
        assert "about 12 s" in w.verify_page.confirm.text()                # 21 chunks × 0.2 s + 8 s
        w.close()
