# T3x Safe Updater: Integrated Development Report

**Living document.** Every session adds a dev log in [`docs/devlog/`](devlog/) and updates the registers below. When fixing, amending or extending the tool, start here: the invariants (§3) and the behaviour register (§5) say what must not change, and the tests that guard each rule.

| | |
|---|---|
| Last updated | Session 05c, 2026-10-14 |
| Terms | **Session** = one AI-assisted development session; **delivery** = the zip snapshot it produced, applied with `./aixun apply` (README, "How this project is developed") |
| Package version | `0.1.0` |
| Target platform | Linux (tested: Raspberry Pi 5, Kali Linux). Windows is out of scope for now (driver issue, §9) |
| Licence | GPL-2.0-or-later |

---

## 1. Status at a glance

| Component | State | Tests | Hardware-verified |
|---|---|---|---|
| Reference scripts (`tests/reference/`) | Frozen | Oracle for equivalence tests | ✅ 2026-10-08, T3BS 1.06 → 1.16 |
| Core: image, protocol, link, flasher, probe, logfile, changelog | Done | 42 | ✅ probe (2026-10-11) and flash path (GUI flashes, 2026-10-11) |
| Simulator (`t3x-sim`) | Done; re-enumeration now changes the device name (02) | Used by 40 tests | n/a |
| CLI: `t3x-probe`, `t3x-update`, `t3x-image` | Done | 10 + 3 equivalence | ✅ `t3x-probe` on the Pi; `t3x-update` ⏳ |
| Compatibility wrappers (`t3x_probe.py`, `t3xupdate_safe.py`) | Done | via CLI tests | ⏳ pending |
| Workspace manager (`tools/aixun.sh`) + `docs/WORKFLOW.md` | Done (01b), corrected (01c), `gui` command (02) | Dry runs, shellcheck | ✅ `setup`, `test`, `probe` on the Pi |
| GUI (`t3x-gui`, PySide6) | Done (02); hot-plug fixed (02b); history + online (03) | 11 end-to-end (offscreen, simulator) | ✅ flashed T3BS 1.16 → 1.15 → 1.16 on the Pi (2026-10-11) |
| Flash history (`core/history.py`) | Done (03) | 4 | Written by every flash from 03 on |
| Online catalogue (`core/online.py`, `t3x-online`) | Done (03); faster + saved list (03a) | 21 | ✅ live list on the Pi (2026-10-12) |
| Workspace settings, flash estimate, history import, update notice (04) | Done | 8 | ✅ in use on the Pi (reported by the maintainer) |
| Publication: INSTALLATION, CONTRIBUTING, LICENSE, CI, check-publish (05) | Done | CI on first push | n/a |

---

## 2. Architecture

```
            ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 front-ends │ t3x-probe    │   │ t3x-update   │   │ t3x-gui      │   t3x-image (offline)
            └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
                   │  events (LogEvent, StageEvent, ProgressEvent, PortsEvent)
                   │  callbacks (confirm(preflight) -> bool)
            ┌──────┴──────────────────┴──────────────────┴───────┐
 core       │ probe.py (whitelist)      flasher.py (state machine) │
            │ image.py  protocol.py  link.py (SerialLink, Timing)  │
            │ logfile.py  crc.py  events.py                        │
            └──────────────────────────┬───────────────────────────┘
                                       │ port_lister()  /  pyserial
                     ┌─────────────────┴──────────────────┐
                     │ real station (/dev/ttyUSBx)  or    │
                     │ t3x-sim on a pty (T3X_SIM_PORTS)   │
                     └────────────────────────────────────┘
```

### 2.1 Module reference

| Module | Responsibility | Key API |
|---|---|---|
| `core/crc.py` | CRC-16/MODBUS | `crc16_modbus(data)` |
| `core/image.py` | Parse and validate JCID images; chunking; scan; diff | `load`, `parse_bytes`, `require_valid`, `FirmwareImage.chunks()`, `scan_directory`, `diff_images` |
| `core/protocol.py` | Command constants; reply parsing; start command | `parse_version`, `start_command`, `READ_ONLY_COMMANDS` |
| `core/events.py` | Event types, `Stage` enum | `Stage`, `LogEvent`, `StageEvent`, `ProgressEvent`, `PortsEvent` |
| `core/link.py` | Discovery, connect/reconnect, idle-based transfer | `SerialLink`, `PortInfo`, `Timing`, `system_port_lister`, `LinkError`, `LinkTimeout` |
| `core/flasher.py` | Complete update procedure | `Flasher(image, link, emit, confirm).run() -> FlashResult`, `Preflight` |
| `core/probe.py` | Read-only checks | `find_station`, `ProbeSession`, `run_probe -> ProbeReport` |
| `core/logfile.py` | Log format; parse logs to find where an update stopped | `file_handler`, `LogSink`, `parse_log -> LogSummary`, `latest_log` |
| `core/changelog.py` | Vendor changelog for T3B/T3BS 1.01–1.16 | `between(product, installed, target)` |
| `core/environment.py` | Host facts, read-only: simulator mode, ModemManager active | `simulated`, `modemmanager_active`, `MM_NOTE` |
| `core/history.py` | `results/history.jsonl`, one line per attempt | `make_record`, `append`, `load`, `summary` |
| `core/online.py` | Catalogue from aixun-updates.github.io: data host from its `config.js`, download, two-address comparison, provenance | `fetch_catalog`, `download`, `compare_local` |
| `sim/station.py` | Simulated station on a pty; each re-enumeration gets a new `ttyUSB<n>` alias; injected faults fire once | `SimStation(Scenario(...))`, `.frames`, `.rx_stream`, `t3x-sim` |
| `gui/app.py` | `t3x-gui` entry point; `--sim` runs a simulated station in-process | `main(argv)` |
| `gui/window.py` | Main window and the five pages; port polling; report export | `MainWindow(Settings)` |
| `gui/workers.py` | Probe and flash jobs on a `QThread`; flash re-checks the station before writing | `ProbeJob`, `FlashJob`, `Expected`, `start` |
| `gui/widgets.py`, `gui/theme.py` | Chunk map, step list, banners, tables, log view; dark QSS theme | `ChunkMap`, `StepList`, `LogView` |

### 2.2 Flash state machine

```
LOAD → CONNECT → PREFLIGHT → CONFIRM ─(no)→ ABORTED
                                │
                               yes
                                ↓
                    BOOTLOADER → START → TRANSFER → VERIFY → DONE
            (any step can end in FAILED; LinkError ends FAILED with fatal=True)
```

---

## 3. Safety invariants

These rules must hold after every change. Each is enforced by at least one test.

| ID | Invariant | Enforced by |
|---|---|---|
| S1 | A successful flash sends exactly the same bytes as the hardware-proven `t3xupdate_safe.py` | `test_golden::test_flash_bytes_identical_to_hardware_proven_script` |
| S2 | Every state-changing byte (echo, start command, chunk data) matches upstream `t3xupdate.py` | `test_golden::test_state_changing_bytes_identical_to_upstream` |
| S3 | The probe can only send `JC_identity`, `JC_version` and, when opted in, `JC_hardware`. The version echo is impossible | `test_probe::test_echo_of_version_string_is_refused`, `test_probe_reports_station_and_sends_only_queries`, `test_golden::test_probe_queries_identical_to_reference` |
| S4 | Nothing beyond read-only queries is sent before the user confirms | `test_flasher::test_abort_sends_only_queries`, `test_cli::test_update_cli_declined_prompt` |
| S5 | An image that fails magic, size, CRC or vector-table checks is never sent; no serial traffic happens at all | `test_image::test_corruption_detected`, `test_vector_table_rejects_wrong_layout`, `test_cli::test_update_cli_refuses_corrupt_file` |
| S6 | Product mismatch blocks the flash in both application and bootloader mode, before any write | `test_flasher::test_product_mismatch_refused_before_any_write`, `test_bootloader_product_mismatch_refused` |
| S7 | Every failure message says whether a re-run is safe and never suggests powering off mid-transfer | Message text in `flasher.py`; `test_interrupted_transfer_then_recovery`, `test_bad_ack` |
| S8 | An interrupted transfer is recoverable by re-running; the tool detects `JC_boot` and completes the update | `test_flasher::test_interrupted_transfer_then_recovery`, manual run (session 01 §4.2) |
| S9 | Success requires reading back `JC_User` and the new version string | `test_flasher::test_verify_detects_station_not_back_in_app` |
| S10 | Any OS-level I/O error while the device vanishes (`SerialException`, `OSError`, `termios.error`) counts as "device lost", never a crash. At the planned resets (echo, last chunk) it is the expected drop | `tests/test_device_loss.py` (5 tests) |
| S11 | The GUI only flashes an image whose product matches the probed station, after the user ticks the confirmation; the flash job re-reads identity and version and aborts with nothing written if they differ from what was verified | `test_gui::test_mismatched_image_cannot_be_flashed`, `test_station_changed_after_verify_writes_nothing` |
| S12 | The GUI cannot be closed and offers no Abort button while bytes are being written | `MainWindow.closeEvent`; Abort permanently disabled on the Flash page |
| S13 | The confirmation tick applies to one file: selecting a different image (path or SHA-256) clears it. The checked file is named with its SHA-256 above the checks | `test_gui::test_manually_added_files_are_checked_and_confirmation_resets` |

---

## 4. Protocol and file-format reference

The full tables are in the README (§8 "Technical notes"). Facts observed on hardware (T3BS, 2026-10-08):

- Entering the bootloader: echoing the version string makes the station drop off USB (no `JC_reset` seen). It re-enumerates as a new tty with the same USB serial number.
- Bootloader `JC_version` reply: `00160000JC_M_T3BS_version1.01`. The meaning of the 8-digit prefix is unknown.
- Start: `0x00028900JC_M_T3BS_version1.01` → `update_jcxx`.
- Chunks: 81 × 2048 B + 1 × 256 B; `ack_jcxx` per chunk; USB drop instead of an ACK after the last one.

---

## 5. Behaviour register (changes vs the hardware-proven scripts)

| ID | Session | Change | Wire bytes affected? |
|---|---|---|---|
| B1 | 01 | Product check in bootloader mode, using the bootloader string; `--allow-unknown-product` override | No (uses an existing reply) |
| B2 | 01 | Clean errors instead of tracebacks when the device is lost in pre-flight, start or verify | No |
| B3 | 01 | Warnings and errors never share a line with the progress counter | No |
| B4 | 01 | `t3x-update` reports an interrupted previous log in the same folder | No |
| B5 | 01 | Pre-flight labels the bootloader version as such; recovery and same-version notes | No |
| B6 | 01 | Final progress shows 100% when the last chunk is answered by a USB drop | No |
| B7 | 01 | The probe explains bootloader state instead of "do not flash yet" | No |
| B8 | 01 | Pure-Python CRC replaces `crcmod` | No |
| B9 | 01a | `termios.error`/`OSError` during write/flush/read handled as device loss (the reference script had the same latent crash risk at the two planned resets) | No |
| B10 | 01a | The probe reports a disconnect with a clean error and exit 1 | No |
| B11 | 02 | With `--port`, if that port vanishes after a reset the link follows the same USB serial number to its new device name (the original would wait on the dead name) | No |
| B12 | 02 | `t3x-probe --json-out FILE`: one probe run gives both the console report and the JSON (previously two runs) | No |
| B13 | 02 | Failure results record the transfer time up to the failure | No |
| B15 | 03 | Simulator logs/history in `results/sim/`; `latest_log` skips simulator logs | No |
| B16 | 03 | Downgrade and ModemManager notices in `t3x-probe`/`t3x-update`; history record per attempt | No |
| B14 | 02b | `run_probe` stops after the first unanswered query (`NoReply`), reports open failures as `PortUnavailable`, and can be cancelled | Fewer bytes to a **silent** station only (1 query instead of 26); unchanged when it answers |

---

## 6. Decision log

| ID | Session | Decision | Rationale |
|---|---|---|---|
| D0 | 00 | Linux-only flashing via `ftdi_sio`; Windows postponed | FTDI driver rejection, Memory Integrity, signature enforcement |
| D1 | 01 | Core emits events and never prints or prompts | One engine for the CLI and the GUI |
| D2 | 01 | Port discovery is injected (`port_lister`) | Simulator and tests without monkeypatching |
| D3 | 01 | `T3X_SIM_PORTS` makes the real front-ends use the simulator | GUI development without an iron |
| D4 | 01 | One `Timing` object; defaults = original | Fast tests; behaviour unchanged |
| D5 | 01 | Pure-Python CRC | Removes a dependency that fails to build |
| D6 | 01 | The simulator runs on a real pty | Exercises pyserial's real device-loss path |
| D7 | 01 | Original scripts frozen in `tests/reference/` | Oracle for the equivalence tests |
| D8 | 01 | Whitelist enforced inside `ProbeSession` | The GUI can't bypass it |
| D10 | 01a | Device loss is a single exception type (`DeviceLost`) raised only by the link and the probe session; front-ends never see raw OS errors | One place to get it right; S10 |
| D11 | 01b | The workspace script lives in the repo (`tools/aixun.sh`), symlinked to the workspace root | Versioned with the code; a rollback restores the matching script |
| D12 | 01b | `venv/ firmware/ results/ deliveries/` live outside `project/` | Deliveries can never touch user files; git never sees firmware or logs |
| D13 | 01b | Deliveries on `delivery/<name>` branches, accepted with `--no-ff` merges | One identifiable merge per delivery |
| D14 | 01b | `./aixun test` sets `T3X_FW_DIR=firmware/` | Real-image tests run automatically |
| D15 | 01b | GUI dependencies installed only once the GUI exists | No PySide6 download before it is needed |
| D16 | 01c | Delivery zips use `project/` as their top folder; `setup` refuses nested layouts unless overridden | Removes the manual rename that caused the Pi's nested setup |
| D9 | plan | GUI: PySide6-Essentials (LGPL), QThread worker, Fusion + QSS dark theme | Chosen over Tkinter (threading, DPI, look) and Tauri (rewrite risk) |
| D17 | 02 | The GUI is a front-end on the same core: `Flasher` runs unchanged in a `FlashJob`; no GUI code sends bytes | S1–S10 keep holding; the golden tests still cover the wire |
| D18 | 02 | The flash re-probes inside its own pre-flight and compares with the Verify page's result (`Expected`) | The station might be swapped or reset between Verify and Flash |
| D19 | 02 | No Abort during transfer; the window refuses to close | Stopping mid-transfer only creates a recovery case |
| D20 | 02 | Bootloader (`JC_boot`) at probe time opens the Recovery page, which reads the newest flash log and lists matching images | Most common real failure: an earlier interrupted flash |
| D21 | 02 | `t3x-gui --sim` runs the simulator in the same process | Try the full GUI flow with one command, no iron |
| D23 | 02b | A new station settles 1.5 s before the auto-probe; silent/busy ports are retried for 30 s; probes never lock the controls | Hot-plug on the Pi; the cause of the silent first seconds is unknown, so the GUI must cope with any of them |
| D30 | 04 | Venv reinstalled only when `pyproject.toml` changes (stamp in venv/) | Code-only deliveries work offline |
| D31 | 04 | GUI preferences and Qt's own settings live in the workspace's `config/` | Self-contained workspace, nothing in `~/.config` |
| D32 | 04 | Background results are always delivered to QObject methods | PySide6 runs plain closures in the worker thread |
| D24–D29 | 03 | Online catalogue: follow the site's `config.js`; https only; second address for comparison only; image checks + no overwrite; `.source.json` provenance; never auto-download or auto-flash | See [session-03.md](devlog/session-03.md) §3 |
| D22 | 02 | GUI tests run headless (`QT_QPA_PLATFORM=offscreen`) and are skipped when PySide6 is absent | The suite still runs on machines without Qt |

---

## 7. Test matrix

`pytest` → **104 passed** in the assistant's development container (Python 3.13 and 3.10, PySide6 6.12, session 05); 103 passed + 1 skipped without the real firmware files. CI (GitHub Actions) runs the same suite on every push; the result of its first run had not been confirmed when this was written.

| File | Count | Focus |
|---|---|---|
| `tests/test_golden.py` | 3 | S1, S2, S3. The oracle runs with a `flush()` shim so the planned USB drop can't crash it (02a) |
| `tests/test_image.py` | 15 | CRC, layout, corruption, vectors, scan, diff, real images (needs `T3X_FW_DIR`) |
| `tests/test_flasher.py` | 14 | Success path, every failure path, recovery, forced port followed by serial number |
| `tests/test_probe.py` | 8 | Whitelist, reader test, bootloader classification, fail-fast on silence, cancel, progress |
| `tests/test_cli.py` | 10 | Output, JSON, `--json-out`, exit codes, logs, prompts, `t3x-image` |
| `tests/test_device_loss.py` | 5 | S10: EIO forced at the echo, the last chunk, mid-transfer and in the probe |
| `tests/test_session03.py` | 9 | Fault once, simulator logs apart, downgrade/ModemManager notices, history (CLI and GUI) |
| `tests/test_session04.py` | 6 | Workspace config (nothing written outside), history import, Flash estimate |
| `tests/test_online.py` | 23 | Online catalogue against a local stand-in of the site, incl. the GUI dialog |
| `tests/test_gui.py` | 11 | Full flow; mismatched image; station changed after Verify; interruption → Recovery → resume; unplug; no firmware folder; plugged in after start (silent 4 s); Rescan cancels a probe; port busy then free; unplug during probe and replug; manually added files checked, tick reset, downgrade flagged |

Simulator scenarios available: hot-plug (`start(attached=False)`, `plug(wake_delay)`, `unplug()`), `wake_delay`, `start_in_bootloader`, `reset_ack`, `ack_last_chunk`, `reenum_delay`, `fail_at_chunk`, `bad_ack_at_chunk`, `no_start_ack`, `verify_comes_back_in_boot`, `split_replies`, `hardware_reply`, custom product, version and bootloader string.

---

## 8. Hardware validation log

| Date | Host | Station | Action | Tool | Result |
|---|---|---|---|---|---|
| 2026-10-08 | Pi 5 / Kali | T3B label, T3BS firmware | Probe, 8/8 PASS, reader 100/100 | `t3x_probe.py` (s00) | ✅ |
| 2026-10-08 | Pi 5 / Kali | same | Flash 1.06 → 1.16 | `t3xupdate_safe.py` (s00) | ✅ 82/82, version read back |
| 2026-10-11 | Pi 5 / Kali, Py 3.14.7 | none (simulator) | `pytest` | package (s01) | ❌ 42/1/1: EIO from `tcdrain` at the last chunk, fixed in 01a |
| 2026-10-11 | Pi 5 / Kali, Py 3.14.7, isolated venv | none (simulator) + real images T3B/T3BS 1.16 | `./aixun setup` + `./aixun test` | package (s01c) | ✅ **49 passed** in 121.5 s (incl. equivalence tests and real-image test) |
| 2026-10-11 | Pi 5 / Kali, Py 3.14.7 | none (simulator) | `./aixun test` | delivery 02 | ❌ 57/1: the frozen oracle lost the last-chunk race (EIO); fixed in 02a |
| 2026-10-11 | Pi 5 / Kali, Py 3.14.7 | T3BS 1.16 | `./aixun gui` (read-only) | delivery 02 | ⚠ Station found when plugged in before start; plugged in after start → probe locked the controls for a long time. Fixed in 02b |
| 2026-10-11 | Pi 5 / Kali, Py 3.14.7 | T3BS (station reports **1.16**: the 2026-10-08 flash persisted) | `./aixun probe JC_M_T3BS_1.16.bin` (read-only) | package (s01c) | ✅ 8/8 PASS, reader test 100/100, latency 5–61 ms, "same version – re-flash" |
| 2026-10-11 23:49 | Pi 5 / Kali, Py 3.14.7 | T3BS | **Downgrade 1.16 → 1.15** | `t3x-gui` (s02c) | ✅ 82/82, drop after echo 0.26 s, bootloader on ttyUSB1, transfer 16.5 s, back on ttyUSB0 as `JC_User` **1.15** |
| 2026-10-11 23:51 | Pi 5 / Kali, Py 3.14.7 | T3BS | **Upgrade 1.15 → 1.16** | `t3x-gui` (s02c) | ✅ 82/82, transfer 16.7 s, read back **1.16**. The version change proves both writes landed |
| 2026-10-12 | Pi 5 / Kali, Py 3.14.7 | none | `./aixun online list -v`, `online compare` | delivery 03a | ✅ list revalidated with HTTP 304 (0.33 s + 0.85 s, both via IPv4); local `JC_M_T3BS_1.15.bin` and `JC_M_T3BS_1.16.bin` **byte-identical** to the site's copies (SHA-256 96808fb8… and 9157cb06…) |
| by 2026-10-14 | Pi 5 / Kali, Py 3.14.7 | T3BS | GUI tested throughout; **1.16 → 1.15 → 1.16 again** | `t3x-gui` (s04) | ✅ reported by the maintainer (logs not reviewed) |

---

## 9. Known limitations and backlog

| ID | Item | Status |
|---|---|---|
| L1 | Flash path of the package on the real station | **Closed** 2026-10-11: two GUI flashes (1.16 → 1.15 → 1.16). The CLI `t3x-update` shares the engine but has not itself flashed hardware |
| L2 | Bootloader product check is based on one observed bootloader string | Open; override available |
| L3 | Last-chunk ACK vs drop: both handled, only drop observed (3 of 3 real flashes) | Monitor |
| L4 | `--hardware` reader test covers only the two core queries | Accepted |
| L5 | Rollback to older firmware | **Closed** for one step (1.16 → 1.15 and back). Larger downgrades untested |
| L6 | Windows: needs WinUSB (Zadig) plus a userspace FTDI path, or proof that firmware 1.08+ fixed the driver issue | Out of scope (Linux first) |
| L7 | macOS untested | Out of scope |
| L8 | The frozen `tests/reference/t3xupdate_safe.py` keeps the S10 issue on purpose (it is the byte oracle). Do not use it to flash. Since 02a the golden test shields it with a `flush()` shim, because the issue made that test flaky on the Pi | Accepted; root wrapper uses the fixed package |
| L9 | On the Pi, pyserial was loaded from Kali's system packages, not the venv | `./aixun status` shows where it loads from; `./aixun rebuild-venv` fixes it |
| L10 | Simulator-based tests depend on thread timing. Two races found and fixed (01b; 02a: the oracle at the last chunk, now verified with the race forced); flakiness was checked with 12 repeated runs | Re-run on failure; report any repeat |
| L11 | GUI never run on the Pi yet: PySide6 6.12 on Python 3.14 / aarch64 and Kali's X11 or Wayland session are untested | **Closed**: GUI used on the Pi from 02b onwards, including the GUI flashes 1.16 → 1.15 → 1.16 (twice). Other desktops: ROADMAP H4 |
| L12 | Qt needs `libxcb-cursor0`, `libxkbcommon-x11-0`, `libegl1` and glibc ≥ 2.39 (PySide6 6.12 wheels); `./aixun setup`/`apply` warn if missing | Documented in INSTALLATION.md §1–2 |
| L13 | The station now runs 1.16 and `JC_M_T3BS_1.16.bin` is in `firmware/`, so a rollback image for the installed version exists. `JC_M_T3BS_1.06.bin` is only needed to go back to 1.06 | Closed |
| L14 | Silent or busy first seconds after plugging the station into the Pi: cause not confirmed. 2026-10-11: ModemManager is **active** on the Pi and logged `port ttyUSB0 released by device …usb1/1-1`, so it does track the station's port; whether it sends AT probes to it is not shown at its default log level. GUI retries; INSTALLATION.md §8 has a read-only check and an optional udev rule. Before a flash: consider stopping ModemManager temporarily (the station re-enumerates twice) | Open, mitigated |
| L15 | Simulator: `--sim-fail-at-chunk N` fails **every** transfer, so Resume in the GUI demo fails again at chunk N (seen in the Pi's 21:45 logs). Real cable pulls happen once | **Closed** in 03 |
| L16 | Simulator flash logs are written to the same `results/` as real ones; the Recovery page reads the newest log, which could be a simulator log | **Closed** in 03 |
| L17 | Recovery from an interrupted **real** transfer still untested on hardware (only simulated) | Open; deliberate test not recommended |
| L18 | Online catalogue against the live site | **Closed** 2026-10-12: correct list on the Pi. Slowness fixed in 03a (cause most likely IPv6 fallback; `-v` confirms) |
| L20 | `./aixun apply` needed the internet even when dependencies were unchanged | **Closed** in 04 (effective from the delivery after 04) |
| L21 | Earlier GUI runs may have left `~/.config/QtProject.conf` (Qt file-dialog history) | Harmless; delete if wanted. From 04 Qt's settings stay in the workspace |
| L19 | Owner of the second download address (`aixun-file.oss-cn-shenzhen.aliyuncs.com`) not confirmed; used only to compare bytes | Accepted |

### Feature backlog

Moved to [ROADMAP.md](../ROADMAP.md) (planned work, help wanted, good first issues, out of scope).

---

## 10. Session index

| Session | Date | Summary | Log |
|---|---|---|---|
| 00 | 2026-10-08/09 | Probe, hardened updater, README; first hardware flash T3BS 1.06 → 1.16 | [session-00.md](devlog/session-00.md) |
| 01 | 2026-10-11 | Core engine, simulator, CLI refactor, 44 tests, byte-identical to the proven script | [session-01.md](devlog/session-01.md) |
| 01a | 2026-10-11 | Fix from the Pi test run: `termios.error` (EIO) on device loss; 5 regression tests; 49 passed | [session-01a.md](devlog/session-01a.md) |
| 01b | 2026-10-11 | Self-contained workspace (`aixun/{project,venv,firmware,results,deliveries}`), `tools/aixun.sh`, rewritten WORKFLOW; dry run passed | [session-01b.md](devlog/session-01b.md) |
| 01c | 2026-10-11 | Workspace corrections after the first real setup: layout check, visible progress, firmware prerequisites, path-agnostic docs | [session-01c.md](devlog/session-01c.md) |
| 02 | 2026-10-11 | PySide6 GUI (five pages, simulator mode, report export), changelog, forced-port fix, `--json-out`; 58 passed | [session-02.md](devlog/session-02.md) |
| 02a | 2026-10-11 | Pi test run of 02: golden test made immune to the last-chunk race in the frozen oracle; `t3x` logger leak between tests fixed | [session-02a.md](devlog/session-02a.md) |
| 02b | 2026-10-11 | First GUI run on the Pi: hot-plug made robust (settle, auto-retry, cancellable probe, controls never locked, live progress); 65 passed | [session-02b.md](devlog/session-02b.md) |
| 02c | 2026-10-11 | Manual firmware selection: confirmation no longer carries over to another file; checked file named with SHA-256; downgrade warning; 66 passed | [session-02c.md](devlog/session-02c.md) |
| 03 | 2026-10-12 | One-shot simulator faults, simulator records apart, downgrade + ModemManager notices, flash history, firmware online from aixun-updates.github.io; 90 passed | [session-03.md](devlog/session-03.md) |
| 03a | 2026-10-12 | Online list: IPv4 first with short connect timeouts, gzip, saved list with revalidation and offline use, `-v` timings; 96 passed | [session-03a.md](devlog/session-03a.md) |
| 04 | 2026-10-12 | Offline-friendly apply + `reinstall`, preferences in `config/gui.json`, Flash speed/ETA, history import, opt-in newer-version notice, GUI-thread fix; 104 passed | [session-04.md](devlog/session-04.md) |
| 05 | 2026-10-14 | New public repository `aixun-t3x-safe-flasher` prepared (one clean commit; revised the same day from an initial plan to reuse the console-scripts repository): INSTALLATION.md, CONTRIBUTING.md, MAINTAINERS.md, LICENSE, CHANGELOG, CI, check-publish, distro-aware script, `.gitignore` fix; version 0.1.0 | [session-05.md](devlog/session-05.md) |
| 05b | 2026-10-14 | Published on GitHub (v0.1.0). ROADMAP.md (help wanted, good first issues, planned, out of scope), folder structure in README, MAINTAINERS.md rewritten with explicit commands and the token procedure. 05c–05d: public docs made generic (no personal paths), AI-assisted development explained, WORKFLOW/INSTALLATION/SCRIPTS_GUIDE de-duplicated | [session-05b.md](devlog/session-05b.md) |
| 06 | planned | See ROADMAP.md P1–P3: install without the workspace, desktop menu entry, T3A groundwork | n/a |

---

## 11. How to amend this project

Applying and testing a zip snapshot (`./aixun apply`, `accept`, `rollback`): [`WORKFLOW.md`](WORKFLOW.md) §3. Pull requests: [CONTRIBUTING.md](../CONTRIBUTING.md).


1. Read §3 and §5 first. If a change would alter the wire bytes, it needs a new equivalence argument and a hardware test before merging.
2. Reproduce bugs in the simulator first (`Scenario(...)`) and add a failing test.
3. Each session adds `docs/devlog/session-NN.md` (template: goal, what was built, decisions, behaviour changes, verification, bugs, limitations, hardware test plan).
4. Update this report: §1 status, new rows in §5 and §6, the counts in §7, §8 after any hardware run, §9, and §10.
5. Never commit vendor `.bin` files or flash logs (`.gitignore` covers both). Real-image tests use `T3X_FW_DIR`.
