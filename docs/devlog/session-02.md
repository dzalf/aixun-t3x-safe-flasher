# Session 02: PySide6 GUI

| | |
|---|---|
| Date | 2026-10-11 |
| Goal | A graphical updater on top of the session-01 core, testable without the iron |
| Outcome | `t3x-gui` with five pages and a built-in simulator; 6 headless end-to-end GUI tests; two core fixes found while building it; **58 passed** |
| Wire bytes changed? | No. The GUI runs the unchanged `Flasher`; the golden tests still pass |
| Input from the Pi | `./aixun probe JC_M_T3BS_1.16.bin`: 8/8 PASS, reader test 100/100, station already on **1.16** (the 2026-10-08 flash persisted) |

## 1. What was built

| Page | What it does |
|---|---|
| **Connect** | Polls the serial ports every second; lists them with VID:PID, driver and serial; probes automatically when one station appears (read-only: `JC_identity`, `JC_version`, 10× link test). Sticker vs firmware note (a "T3B" label can run T3BS firmware) |
| **Verify** | Firmware library from `firmware/` (or **Folder…** / **Add file…**), best match pre-selected, incompatible images flagged with the reason. Checks table (station + image) beside the changelog since the installed version. Warns when there is no rollback image for the installed version. **Flash firmware** stays disabled until every check passes and the confirmation box is ticked |
| **Flash** | Percentage, stage, progress bar, a tile per 2048-byte chunk (pending / sending / acknowledged / failed), live log in readable form ("chunk 31/82", "ack_jcxx [12 ms]"). No Abort button; the window refuses to close while writing |
| **Done** | Success, failure or cancelled variant: chunks and bytes sent, duration and transfer time, bootloader string, log file name, a "what to do now" list, **Resume / retry**, **Open results folder**, **Export report…** (JSON: probe, image, result, log path) |
| **Recovery** | Opens when the station answers `JC_boot`. Shows the bootloader string, a summary of the newest flash log (where it stopped) and the images that match the bootloader's product; **Resume flash** asks for confirmation first |

Station box (left column): product, firmware, mode, the last characters of the USB serial. After a failure it shows `— (incomplete)` / `JC_boot (waiting)` instead of stale data.
If the station is unplugged at any time outside a flash, the GUI returns to Connect.

`t3x-gui --sim` starts a simulated station in the same process (options: `--sim-product`, `--sim-version`, `--sim-bootloader`, `--sim-fail-at-chunk N`); the title bar says **[SIMULATED STATION]**.
`./aixun gui` runs it with `firmware/` and `results/` of the workspace.

New core module `core/changelog.py`: the vendor changelog for T3B/T3BS 1.01–1.16, and `between(product, installed, target)`.

## 2. Design decisions

| ID | Decision | Rationale |
|---|---|---|
| D17 | The GUI is a front-end only; `Flasher` runs unchanged inside `FlashJob` on a `QThread` | Every safety rule and test of the core keeps applying |
| D18 | `FlashJob`'s confirm callback compares the station's identity and version string with what Verify saw; any difference aborts with nothing written | The station may be swapped, reset or re-plugged between the two pages |
| D19 | No Abort during transfer; closing is refused | Stopping mid-transfer can only create a recovery case |
| D20 | `JC_boot` at probe time → Recovery page | An interrupted earlier flash is the most likely real-world failure |
| D21 | Simulator in-process for `--sim` | One command to try the whole flow |
| D22 | GUI tests headless (`offscreen`), skipped without PySide6 | Suite runs anywhere |

## 3. Core changes found while building the GUI

| # | Problem | Fix | Test |
|---|---|---|---|
| 1 | With an explicit `--port`, after the reset into the bootloader the station re-enumerates under a **new** name (`ttyUSB0` → `ttyUSB1`); the link kept waiting for the old one. The CLI only worked because it auto-detects by default. The simulator hid this, because its pty names were reused | `SerialLink` records the USB serial number on the first connect and, when the forced port is gone, follows that serial to its new device (logged as "… is gone; following serial …") | `test_flasher::test_forced_port_survives_reenumeration` (fails on the old code, passes on the new) |
| 2 | The simulator's re-enumeration could reuse the same pty name | Each re-enumeration now gets a fresh `ttyUSB<n>` alias, like the real kernel | Same test, and all 40 simulator-based tests |
| 3 | `./aixun probe` ran the probe twice (text, then JSON) | `t3x-probe --json-out FILE` writes the JSON of the same run | `test_cli::test_probe_json_out_is_the_same_run` |
| 4 | A failed flash reported transfer time 0.0 s | `FlashResult.transfer_seconds` set on failure too | GUI failure page |

## 4. GUI issues found in the rendered screenshots and fixed

| Issue | Fix |
|---|---|
| Verify page too tall; the check list scrolled | Checks and changelog side by side |
| Flash subtitle wrapped | Kept to a single line |
| Raw chunk bytes in the log | Readable "chunk n/N" and "ack_jcxx [ms]" lines |
| Failure page showed the full image size as sent | Shows bytes actually sent and transfer time |
| Station box stale after a failure | Updated to incomplete / waiting |
| "driver ?" on Connect | Driver name shown only when the kernel reports it |
| Messages told GUI users to "re-run this script" | Rewritten for the GUI ("click Resume / retry") |

## 5. Verification

| Check | Result |
|---|---|
| `pytest` (container, Python 3.13, PySide6 6.12) | **58 passed** in 157 s |
| `test_gui.py` | 6/6: full flow; mismatched image cannot be flashed; station changed after Verify writes nothing; cable pull → failure page → Recovery → resume → success; unplug → Connect; no firmware folder explained |
| Golden tests (S1–S3) | Pass: wire bytes unchanged |
| Screenshots | All six pages rendered offscreen and inspected (`docs/img/`) |
| `shellcheck tools/aixun.sh` | Clean (including info level) |
| Delivery rehearsal | Fresh workspace built from `t3x_session01c.zip` (the state on the Pi), then `./aixun apply t3x_session02.zip` with the **01c** script: PySide6 installed with progress, `./aixun test` 58 passed |
| `t3x-gui --sim` entry point | Ran 10 s headless without errors |

## 6. Workspace and docs

| Change | Where |
|---|---|
| `./aixun gui [--sim …]` | `tools/aixun.sh` |
| `./aixun gui` and `t3x-gui` stop with a plain message when there is no desktop session (instead of Qt's "no Qt platform plugin could be initialized" abort, seen when testing the delivery in a fresh workspace) | `tools/aixun.sh`, `gui/app.py` |
| `apply`/`setup` warn when the Qt libraries or glibc ≥ 2.39 are missing, and say PySide6 is an ~85 MB download | `tools/aixun.sh` |
| GUI prerequisites (item 6), `apt` line, "Starting over" §3.0, GUI commands, GUI troubleshooting | `docs/WORKFLOW.md` |
| GUI section with screenshot | `README.md` §9 |

## 7. Limitations

| ID | Item |
|---|---|
| L11 | Not yet run on the Pi: PySide6 6.12 on Python 3.14 / aarch64 and Kali's desktop session are untested |
| L12 | Needs `libxcb-cursor0 libxkbcommon-x11-0 libegl1` and glibc ≥ 2.39 |
| L13 | Closed: the station runs 1.16 and that image is in `firmware/`; 1.06 is only needed to downgrade |

## 8. Hardware test plan for this session

| # | Step | Station? | Writes? | Expected |
|---|---|---|---|---|
| 1 | `./aixun apply t3x_session02.zip` | No | No | Branch `delivery/t3x_session02`; PySide6 installed with visible progress |
| 2 | `./aixun test` | No | No | 58 passed |
| 3 | `./aixun gui --sim` | No | No | Full flow to "Update successful" against the simulator |
| 4 | `./aixun gui --sim --sim-fail-at-chunk 31` | No | No | Failure page → Resume / retry → Recovery → success |
| 5 | `./aixun gui` with the station | Yes | **No** (Connect, Verify only) | Station T3BS 1.16, JC_User, all checks PASS, "same version (re-flash)" status |
| 6 | Optional: **Flash firmware** with 1.16 | Yes | Yes | 82/82, "Update successful", report exported |
