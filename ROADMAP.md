# Roadmap and help wanted

What is planned, where help is wanted, and what is deliberately out of scope. This file is the master
list. Items are also opened as GitHub issues labelled `help wanted` or `good first issue`; the issue is
where the discussion happens.

**To take something on:** comment on its issue (or open one, naming the item, e.g. "H2"), so two people
don't do the same work. Then follow [CONTRIBUTING.md](CONTRIBUTING.md). Read its ground rules first:
the bytes sent to the station must not change silently.

The IDs `L2`, `L14` … refer to the limitations table in
[docs/DEVELOPMENT_REPORT.md](docs/DEVELOPMENT_REPORT.md) §9.

---

## 1. Help wanted

| ID | What | What we need from you | Station needed? |
|---|---|---|---|
| H1 | **Other station models**: T3A, T320, T420D, and other T3B/T3BS variants. Only one station (a T3B-labelled unit that reports T3BS) has been tested | Run the **read-only** probe (`./aixun probe` or `t3x-probe`) and post the result with the "Hardware report" issue template. No flashing needed | Yes |
| H2 | **Other distributions**: the Fedora, openSUSE and Arch instructions in INSTALLATION.md §2 are written from the package names and have not been run | Follow INSTALLATION.md on that distribution and report each step that differed (package names, serial group, Qt libraries) | No |
| H3 | **Other host machines**: a PC (x86_64) with a real station, and other ARM boards (Raspberry Pi 4, other single-board computers) | Probe report plus your board, distribution and Python version | Yes |
| H4 | **GUI on other desktops**: GNOME, KDE, Xfce, on Wayland and X11 | Does the window open, do the dialogs work, any warnings in the terminal? Screenshots welcome | No (`./aixun gui --sim`) |
| H5 | **ModemManager** (L14): does it send modem (AT) commands to the station's serial port when it's plugged in? | The output of the ModemManager check in INSTALLATION.md §8 (`journalctl …`), run right after plugging the station in. Read-only | Yes |
| H6 | **Bootloader strings of other models** (L2): the product check in bootloader mode is based on one observed string, `00160000JC_M_T3BS_version1.01` | If you flash another model, the flash log shows its string: post that line, with the USB serial number replaced | Yes (only if you flash anyway) |
| H7 | **Recovery after a real interrupted transfer** (L17): only tested with the simulator | **Please don't cause one on purpose.** If it happens to you, post the flash log (serial replaced) and what you did to recover | Only if it happens |

## 2. Good first issues (no station needed)

| ID | What | Where to start |
|---|---|---|
| G1 | A `--version` option that prints the package version on `t3x-probe`, `t3x-update`, `t3x-image`, `t3x-online`, `t3x-history` and `t3x-gui`. (`t3x-sim` already uses `--version` for the simulated firmware version; leave it as it is) | `t3x.__version__` in `src/t3x/__init__.py`; the argument parsers in `src/t3x/cli/` and `src/t3x/gui/app.py`; one test in `tests/test_cli.py` |
| G2 | An example udev rule that gives the station a stable name such as `/dev/aixun-t3x`, plus a short section in INSTALLATION.md §8. Match on the serial number prefix `JCID_`, not only on the USB IDs `0403:6001`, which every FTDI adapter shares | INSTALLATION.md §8 already has an optional udev rule for ModemManager |
| G3 | A linter in the test workflow (for example `ruff check`), with the findings fixed | `.github/workflows/tests.yml`; keep lines ≤ 120 characters |

## 3. Planned by the maintainer

| ID | What | Why |
|---|---|---|
| P1 | **Install without the workspace**: `pipx install` straight from GitHub, with a default data folder for firmware, logs and settings. Outside the workspace, the tools currently use `./firmware` and `./results` in whatever folder you start them from | So users who only want to update a station don't need the `./aixun` workspace |
| P2 | **Desktop menu entry** (a `.desktop` file and icon) | Start the GUI from the applications menu |
| P3 | **T3A support groundwork**: simulator profile, image checks and probe for the T3A product line | The maintainer has a T3A to test with |
| P4 | **Publish on PyPI** (after P1) | `pipx install t3x-safe-updater[gui]` without a GitHub address |
| P5 | Show `JC_hardware` in the GUI's advanced panel (read-only query; already supported by the probe when enabled) | More detail in hardware reports |

## 4. Not planned (discussion welcome in an issue)

| What | Why not now |
|---|---|
| Windows support (L6) | The station's USB interface is rejected by current FTDI drivers; it would need WinUSB and a different serial path |
| macOS (L7) | Untested; no one has asked yet |
| A single-file executable (PyInstaller, AppImage) | Linux users install Python tools with `pip`/`pipx` (P1, P4). A bundled build would be 150–250 MB, has to be built separately for x86_64 and ARM, and has to be rebuilt for every release. Reconsider if users ask for it |
| Firmware files in this repository | They are AiXun's. `./aixun online get` downloads them from aixun-updates.github.io |
