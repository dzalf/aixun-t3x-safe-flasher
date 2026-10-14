# SPDX-License-Identifier: GPL-2.0-or-later
"""Session 04: preferences in the workspace, ETA, history import, newer-version notice."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from conftest import ROOT, make_image
from t3x.gui.config import GuiConfig


def test_config_roundtrip_and_bad_files(tmp_path):
    p = tmp_path / "config" / "gui.json"
    c = GuiConfig.load(str(p))
    assert c.firmware_dir is None and c.cross_check and not c.update_notice
    c.firmware_dir, c.geometry, c.update_notice = "/x", [1, 2, 1000, 700], True
    assert c.save()
    d = GuiConfig.load(str(p))
    assert (d.firmware_dir, d.geometry, d.update_notice) == ("/x", [1, 2, 1000, 700], True)
    p.write_text("{not json")
    assert GuiConfig.load(str(p)).geometry == []                     # unreadable: defaults, no crash
    p.write_text(json.dumps({"geometry": "big", "unknown": 1}))
    assert GuiConfig.load(str(p)).geometry == []
    assert not GuiConfig.load(None).save()                           # no path: remember nothing


def test_gui_writes_nothing_outside_the_workspace(tmp_path):
    """Run the real entry point with an empty HOME; afterwards HOME must still be empty
    apart from what the OS's font cache does, and the preferences must be in the workspace."""
    pytest.importorskip("PySide6")
    home = tmp_path / "home"
    home.mkdir()
    ws = tmp_path / "ws"
    (ws / "firmware").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {os.path.join(ROOT, 'src')!r})
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QFileDialog
        import t3x.gui.window as W
        from t3x.gui import app

        orig_show = W.MainWindow.show
        def show(self):
            orig_show(self)
            def act():
                d = QFileDialog(self, "x", {str(other)!r})
                d.setOption(QFileDialog.DontUseNativeDialog)
                d.show(); d.close(); d.deleteLater()            # Qt saves its dialog history on close
                self.s.firmware_dir = {str(other)!r}
                self.cfg.firmware_dir = {str(other)!r}
                self.resize(1000, 700)
                QTimer.singleShot(200, self.close)
            QTimer.singleShot(1500, act)
        W.MainWindow.show = show
        sys.exit(app.main(["--sim", "--config", {str(ws / 'config' / 'gui.json')!r},
                           "--results-dir", {str(ws / 'results')!r}, "--firmware-dir", {str(ws / 'firmware')!r}]))
    """)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
               QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    leftovers = [os.path.relpath(os.path.join(d, f), home) for d, _, fs in os.walk(home) for f in fs]
    assert [x for x in leftovers if not x.startswith(".cache/fontconfig")] == [], leftovers
    cfg = json.loads((ws / "config" / "gui.json").read_text())
    assert cfg["firmware_dir"] == str(other) and len(cfg["geometry"]) == 4 and cfg["geometry"][2] >= 900
    # Qt's own dialog history, if written at all, went to the workspace's config folder too
    assert set(os.listdir(ws / "config")) <= {"gui.json", "QtProject.conf"}


def test_saved_firmware_folder_is_used_next_time(tmp_path, monkeypatch):
    from t3x.gui import app
    seen = {}
    monkeypatch.setattr("t3x.gui.window.MainWindow", lambda s: (seen.update(s=s), _Stop())[1])
    other = tmp_path / "other"
    other.mkdir()
    cfgp = tmp_path / "gui.json"
    GuiConfig(firmware_dir=str(other), path=str(cfgp)).save()
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    with pytest.raises(_StopError):
        app.main(["--config", str(cfgp), "--results-dir", str(tmp_path)])
    assert seen["s"].firmware_dir == str(other) and seen["s"].config.path == str(cfgp)


class _StopError(Exception):
    pass


class _Stop:
    def setWindowTitle(self, *_):
        pass

    def show(self):
        raise _StopError


DATA = os.path.join(ROOT, "tests", "data")


def test_history_import_from_a_real_log(tmp_path):
    """tests/data holds an anonymised copy of the Pi's 2026-10-11 23:51 flash log (1.15 -> 1.16)."""
    import shutil
    from t3x.core import history
    from t3x.core.logfile import SIM_MARKER
    shutil.copy(os.path.join(DATA, "t3x_flash_20261011_235102.log"), tmp_path)
    (tmp_path / "t3x_flash_20261011_214209.log").write_text(f"21:42:09.000 INFO: {SIM_MARKER}\n")
    (tmp_path / "t3x_flash_20261011_200000.log").write_text("20:00:00.000 INFO: hello\n")
    r = history.import_logs(str(tmp_path))
    assert len(r["added"]) == 1 and len(r["skipped"]) == 2
    rec = history.load(str(tmp_path))[0]
    assert rec["ok"] and rec["tool"] == "imported from log" and rec["time"] == "2026-10-11 23:51:02"
    assert (rec["before_version"], rec["after_version"]) == ("JC_M_T3BS_version1.15", "JC_M_T3BS_version1.16")
    assert rec["bootloader"] == "00160000JC_M_T3BS_version1.01" and rec["transfer_s"] == 16.7
    assert rec["chunks_acked"] == rec["n_chunks"] == 82 and rec["usb_serial"] == "JCID_T3B_TESTSERIAL01"
    assert rec["file"] is None and rec["sha256"] is None
    assert history.import_logs(str(tmp_path))["added"] == []          # never twice


def test_history_cli(tmp_path, capsys):
    import shutil
    from t3x.cli import history as cli_history
    shutil.copy(os.path.join(DATA, "t3x_flash_20261011_235102.log"), tmp_path)
    for argv in (["--results", str(tmp_path), "import"], ["--results", str(tmp_path)]):
        with pytest.raises(SystemExit) as e:
            cli_history.main(argv)
        assert e.value.code == 0
    out = capsys.readouterr().out
    assert "1 added, 0 skipped" in out and "T3BS 1.15 → 1.16  OK  82/82  16.7 s" in out and "(imported)" in out


def test_flash_page_eta_uses_history(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import shutil
    from PySide6.QtWidgets import QApplication
    from test_gui import make_window, probe_done, wait_until
    from t3x.core import history
    from t3x.sim import Scenario, SimStation
    app = QApplication.instance() or QApplication([])
    fwdir = tmp_path / "firmware"
    fwdir.mkdir()
    (fwdir / "JC_M_T3BS_1.16.bin").write_bytes(make_image(payload=20 * 2048 + 256))
    res = tmp_path / "results"
    res.mkdir()
    shutil.copy(os.path.join(DATA, "t3x_flash_20261011_235102.log"), res)
    history.import_logs(str(res))
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        w = make_window(app, sim, str(fwdir), tmp_path)
        w.s.results_dir = str(res)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        w.verify_page.confirm.setChecked(True)
        w.verify_page.flash_btn.click()
        assert wait_until(app, lambda: "from 1 earlier T3BS flash" in w.flash_page.rate.text(), 5)
        assert "about 4 s" in w.flash_page.rate.text()                 # 21 chunks × 16.7/82 s
        assert wait_until(app, lambda: "Speed" in w.flash_page.rate.text() or not w.flashing, 30)
        assert wait_until(app, lambda: not w.flashing, 30)
        assert w.flash_page.rate.text().startswith("Transfer finished at")
        w.close()
