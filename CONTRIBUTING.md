# Contributing

Thank you for helping. This project writes firmware into soldering stations, so the bar is
**"never make a station harder to recover"**. The good news: almost all development happens
against a **simulated station**, so you don't need the hardware to contribute.

This is an ordinary Python project (`pyproject.toml`, `src/` layout, `pytest`). Section 2 is all
most contributors need. Section 3 describes the optional `./aixun` workspace the maintainer uses.

**Looking for something to work on?** [ROADMAP.md](ROADMAP.md) lists where help is wanted (many items
need no station, or only the read-only probe) and good first issues. The folder structure is in the
[README](README.md#folder-structure).

---

## 1. Ground rules

| Rule | Why |
|---|---|
| **Wire bytes don't change silently.** A successful flash must send exactly the same bytes as the hardware-proven script (`tests/test_golden.py`). If your change alters what is sent, say so in the pull request and include a hardware report | That byte sequence is what has been proven on real stations |
| **Nothing beyond read-only queries before the user confirms.** The probe may only send `JC_identity`, `JC_version` (and `JC_hardware` when explicitly enabled) | Echoing the version string resets the station into its bootloader |
| **Never commit firmware (`*.bin`), flash logs, `history.jsonl` or reports** | Firmware is the vendor's; logs and history contain the station's USB serial number. `.gitignore` covers them |
| **A bug fix comes with a test that fails without the fix** | The simulator makes almost every failure reproducible |
| **Say what was tested on hardware and what wasn't** | Simulator results and hardware results are different evidence |
| Contributions are accepted under **GPL-2.0-or-later** | The licence of this project and of the original updater |

Before changing anything that touches the station, read `docs/DEVELOPMENT_REPORT.md` §3 (safety
invariants, each with the test that guards it) and §5 (behaviour changes against the proven script).

---

## 2. Standard Python workflow (recommended)

### 2.1 One-time setup

System packages: see [INSTALLATION.md](INSTALLATION.md) §2 (git, Python ≥ 3.10 with `venv`, and the Qt
libraries if you work on the GUI).

```bash
# 1. On GitHub: open https://github.com/dzalf/aixun-t3x-safe-flasher and click "Fork".

git clone https://github.com/<your-user>/aixun-t3x-safe-flasher.git
cd aixun-t3x-safe-flasher
# your fork, in any folder you like

git remote add upstream https://github.com/dzalf/aixun-t3x-safe-flasher.git
# 'upstream' = the main repository, to pick up other people's changes

python3 -m venv .venv
# a private environment inside the clone (ignored by git)

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,gui]"
# editable install: .venv runs the code in src/ directly; 'dev' = pytest, 'gui' = PySide6

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
# expected: all passed except one skipped test (it needs real firmware images; see 2.4)
```

You may activate the environment instead (`source .venv/bin/activate`) and then type `python`,
`pytest`, `t3x-gui` directly.

### 2.2 The everyday cycle

```bash
git switch main && git pull upstream main
# start from the latest main

git switch -c fix/short-description
# one branch per change: fix/…, feature/…, docs/…

# … edit files …

.venv/bin/python -m pytest tests/test_flasher.py -x
# the tests closest to your change first (-x stops at the first failure)

.venv/bin/t3x-gui --sim
# try GUI changes against the built-in simulated station (no hardware)

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
# the full suite before every commit (~4 minutes on a Raspberry Pi 5, less on a PC)

python3 tools/check_publish.py .
# scans your commits for firmware, logs, real USB serial numbers, keys and tokens

git add -A && git commit -m "Short summary in the imperative"
git push -u origin fix/short-description
# then open a pull request against dzalf/aixun-t3x-safe-flasher : main
```

If you change `pyproject.toml` (dependencies, commands), run the `pip install -e ".[dev,gui]"` line again.
GitHub runs the same tests automatically on every pull request (`.github/workflows/tests.yml`).

### 2.3 The simulator

`src/t3x/sim/station.py` is a simulated station on a pseudo-terminal. It speaks the protocol observed
on a real T3BS, including the USB drops when entering the bootloader and after the last chunk, and
re-enumeration under a new device name.

| You want to… | Use |
|---|---|
| Click through the GUI | `t3x-gui --sim` |
| A station stuck in its bootloader | `t3x-gui --sim --sim-bootloader` |
| A cable pull at chunk 31 | `t3x-gui --sim --sim-fail-at-chunk 31` (happens once, like a real pull) |
| A different product line | `t3x-gui --sim --sim-product T3B` |
| Command-line tools against the simulator | Terminal 1: `t3x-sim --ports-file /tmp/sim.json` · terminal 2: `export T3X_SIM_PORTS=/tmp/sim.json`, then `t3x-probe`, `t3x-update FILE.bin` |
| A new fault in a test | `Scenario(...)` fields: `fail_at_chunk`, `bad_ack_at_chunk`, `no_start_ack`, `reenum_delay`, `verify_comes_back_in_boot`, `split_replies`, `wake_delay`, `start_in_bootloader`, … and `SimStation.plug()` / `unplug()` for hot-plug |

### 2.4 Writing tests

```python
from t3x.core import image as fw
from t3x.core.flasher import Flasher
from t3x.core.link import SerialLink, Timing
from t3x.sim import Scenario, SimStation
from conftest import make_image                     # builds a valid synthetic update image

def test_my_case():
    img = fw.parse_bytes(make_image(payload=20 * 2048 + 256))
    with SimStation(Scenario(bad_ack_at_chunk=5)) as sim:
        link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=5)
        result = Flasher(img, link).run()
    assert not result.ok and "Bad ACK at chunk 5" in result.message
```

- GUI tests run headless (`QT_QPA_PLATFORM=offscreen`) and drive the real window: see `tests/test_gui.py`
  (`make_window`, `wait_until`).
- Results from background threads must go to **methods of a QObject**, never a plain function or lambda:
  PySide6 runs plain callables in the worker thread, which then touches widgets and crashes.
- The one test that needs real firmware reads it from `T3X_FW_DIR`
  (`T3X_FW_DIR=/path/to/firmware pytest` with `JC_M_T3B_1.16.bin` and `JC_M_T3BS_1.16.bin` in it).
- Network code is tested against a local stand-in web server (`tests/test_online.py`), never the internet.

---

## 3. Optional: the `./aixun` workspace

The maintainer works in a self-contained folder that keeps the code, its environment, firmware and
results side by side, managed by `tools/aixun.sh`. It's optional; it helps if you also flash real
stations.

```bash
mkdir -p ~/aixun && cd ~/aixun
git clone https://github.com/<your-user>/aixun-t3x-safe-flasher.git project
# the clone must be in a folder called 'project' inside the workspace

./project/tools/aixun.sh setup
# creates venv/, firmware/, results/ next to project/, installs everything, makes ./aixun

./aixun test            # same tests; output saved in results/
./aixun gui --sim       # GUI with the simulator
./aixun probe X.bin     # read-only probe of a real station; report saved in results/
./aixun check-publish   # the pre-push scan of section 2.2
./aixun help            # everything else
```

Day-to-day git commands are the normal ones, run inside `project/` (or with `git -C project …`).
Details: [docs/WORKFLOW.md](docs/WORKFLOW.md).

---

## 4. Testing on real hardware

Only after the full suite passes. Read-only first; writes last.

| Step | Command | Writes to the station? |
|---|---|---|
| 1 | `t3x-probe --fw <image>.bin --reader-test 50` (or `./aixun probe <image>.bin`) | No |
| 2 | `t3x-gui` → Connect and Verify pages only | No |
| 3 | Re-flash the version the station already runs | Yes (lowest risk: firmware known to run on that unit) |
| 4 | Only if your change needs it: a version change | Yes |

Attach to the pull request: the test output, the probe report, the flash log(s) **with the USB serial
number replaced** (e.g. `JCID_T3B_XXXXXXXXXXXX`), the station model, the host (board, distribution,
Python version) and what you did. The "Hardware report" issue template lists the same fields.

---

## 5. Where things are

| Path | Contents |
|---|---|
| `src/t3x/core/` | UI-free engine: `image` (file checks), `protocol`, `link` (serial, reconnect), `flasher` (update state machine), `probe` (read-only), `logfile`, `history`, `online`, `environment`, `changelog` |
| `src/t3x/cli/` | `t3x-probe`, `t3x-update`, `t3x-image`, `t3x-online`, `t3x-history` |
| `src/t3x/gui/` | PySide6 GUI: `window` (pages), `workers` (threads), `widgets`, `theme`, `config`, `app` (entry point `t3x-gui`) |
| `src/t3x/sim/` | Simulated station (`t3x-sim`) |
| `tests/` | pytest suite; `tests/reference/` = frozen original scripts used as byte-level references (don't edit); `tests/data/` = anonymised example logs |
| `tools/` | `aixun.sh` (optional workspace manager), `check_publish.py` (pre-push scan) |
| `docs/` | Development report, per-session devlogs, workflow, scripts guide, screenshots |
| `constraints/tested.txt` | Exact package versions of the reference environment |

Style: follow the surrounding code (type hints, dataclasses, ≤ 120 characters per line, docstrings that
say *why*). Shell code must pass `shellcheck tools/aixun.sh`.

---

## 6. Documentation is part of the change

| Change | Update |
|---|---|
| Behaviour change | `docs/DEVELOPMENT_REPORT.md` §5 (behaviour register) and `CHANGELOG.md` |
| A decision with trade-offs | §6 (decision log) |
| New tests | §7 (test matrix) |
| Hardware test | §8 (hardware validation log) |
| New limitation, or one closed | §9 |
| User-visible commands | README, INSTALLATION.md, WORKFLOW.md |

---

## 7. Reporting a problem

Open an issue with what you did, what happened, what you expected, your distribution and Python version,
and the relevant output (with the USB serial number replaced). The issue templates ask for exactly this.
