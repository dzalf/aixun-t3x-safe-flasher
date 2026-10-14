# SPDX-License-Identifier: GPL-2.0-or-later
"""The CLIs run against the simulator through T3X_SIM_PORTS, as a user would."""
import glob
import json
import os

import pytest

from t3x.cli import image as cli_image
from t3x.cli import probe as cli_probe
from t3x.cli import update as cli_update
from t3x.core import history
from t3x.core.logfile import is_simulated_log, parse_log
from t3x.sim import Scenario, SimStation


@pytest.fixture
def sim_env(tmp_path, monkeypatch):
    ports = str(tmp_path / "ports.json")
    monkeypatch.setenv("T3X_SIM_PORTS", ports)

    def start(**kw):
        return SimStation(Scenario(reenum_delay=0.2, **kw), ports_file=ports)
    return start


def run(main, argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    return e.value.code


def test_probe_human_output(sim_env, image_file, capsys):
    with sim_env():
        code = run(cli_probe.main, ["--fw", image_file(), "--reader-test", "3"])
    out = capsys.readouterr().out
    assert code == 0
    for s in ["=== USB / host side", "Serial number   : JCID_T3B_SIM0000001", "Vector table    : payload 165888 B",
              "6/6 replies complete and identical", "Product (field2): T3BS",
              "[PASS] Update product matches station", "Station v1.06 vs file v1.16",
              "All checks passed. Communication looks safe to proceed."]:
        assert s in out, s


def test_probe_json(sim_env, capsys):
    with sim_env():
        code = run(cli_probe.main, ["--json", "--repeat", "2"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["ok"] and data["product"] == "T3BS" and data["firmware"] == "1.06"
    assert set(data["sent"]) == {"JC_identity", "JC_version"}


def test_probe_wrong_product_fails(sim_env, image_file, capsys):
    with sim_env():
        code = run(cli_probe.main, ["--fw", image_file(product=b"T3B")])
    assert code == 2 and "[FAIL] Update product matches station" in capsys.readouterr().out


def test_update_cli_success_writes_log(sim_env, image_file, tmp_path, capsys):
    with sim_env() as sim:
        code = run(cli_update.main, [image_file(payload=10 * 2048), "--yes", "--log-dir", str(tmp_path)])
    assert code == 0 and sim.version == b"1.16"
    out = capsys.readouterr()
    assert "Station : T3BS v1.06 (JC_User)" in out.out and "11/11 chunks (100%)" in out.out
    # simulator runs are kept apart from real ones (session 03)
    assert glob.glob(os.path.join(tmp_path, "t3x_flash_*.log")) == []
    logs = glob.glob(os.path.join(tmp_path, "sim", "t3x_flash_*.log"))
    assert len(logs) == 1 and parse_log(logs[0]).outcome == "success" and is_simulated_log(logs[0])
    recs = history.load(os.path.join(tmp_path, "sim"))
    assert len(recs) == 1 and recs[0]["ok"] and recs[0]["simulated"] and recs[0]["tool"] == "t3x-update"
    assert recs[0]["before_version"] == "JC_M_T3BS_version1.06" and recs[0]["after_version"].endswith("1.16")
    assert recs[0]["chunks_acked"] == 11 and len(recs[0]["sha256"]) == 64


def test_update_cli_refuses_corrupt_file(sim_env, tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"JCID" + b"\xff" * 400)
    with sim_env() as sim:
        code = run(cli_update.main, [str(bad), "--yes", "--log-dir", str(tmp_path)])
    assert code and "ERROR" in str(code) and sim.frames == []


def test_update_cli_declined_prompt(sim_env, image_file, tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "no")
    with sim_env() as sim:
        code = run(cli_update.main, [image_file(payload=4096), "--log-dir", str(tmp_path)])
    assert code == 1 and set(sim.frames) <= {b"JC_identity", b"JC_version"}


def test_image_cli(image_file, capsys, tmp_path):
    a = image_file("JC_M_T3B_1.16.bin", product=b"T3B", seed=5)
    b = image_file("JC_M_T3BS_1.16.bin")
    assert run(cli_image.main, ["info", b]) == 0
    assert "[PASS] crc" in capsys.readouterr().out
    assert run(cli_image.main, ["scan", str(tmp_path), "--product", "T3BS"]) == 0
    out = capsys.readouterr().out
    assert "JC_M_T3BS_1.16.bin" in out and "JC_M_T3B_1.16.bin " not in out
    assert run(cli_image.main, ["diff", a, b]) == 0
    assert "do not cross-flash" in capsys.readouterr().out


def test_probe_explains_bootloader_state(sim_env, capsys):
    with sim_env(start_in_bootloader=True):
        code = run(cli_probe.main, ["--repeat", "1", "--wait", "2"])
    out = capsys.readouterr().out
    assert code == 2 and "waiting in its BOOTLOADER" in out and "do not flash yet" not in out


def test_update_recovery_labels_bootloader(sim_env, image_file, tmp_path, capsys):
    with sim_env(start_in_bootloader=True) as sim:
        code = run(cli_update.main, [image_file(payload=4096), "--yes", "--log-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0 and sim.version == b"1.16"
    assert "Station : T3BS bootloader v1.01 (JC_boot)" in out and "Recovery:" in out


def test_probe_json_out_is_the_same_run(sim_env, tmp_path, capsys):
    out = tmp_path / "p.json"
    with sim_env() as sim:
        code = run(cli_probe.main, ["--reader-test", "4", "--json-out", str(out)])
    data = json.loads(out.read_text())
    assert code == 0 and "All checks passed" in capsys.readouterr().out
    assert data["reader_test"] == {"n": 4, "mismatches": 0} and len(data["checks"]) == 6
    assert sim.frames.count(b"JC_version") == 3 + 4          # one run only: 3 rounds + 4 reader tests
