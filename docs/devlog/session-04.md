# Session 04: Workspace settings, flash time estimate, history import, update notice, offline apply

| | |
|---|---|
| Date | 2026-10-12 |
| Outcome | Five items done; one GUI threading bug found and fixed; **104 passed** (+8), full suite run twice clean |
| Wire bytes changed? | No |

## 1. What was built

| Item | Details |
|---|---|
| Offline-friendly `apply` | The venv is only reinstalled when `project/pyproject.toml` changes (a stamp in `venv/` records its SHA-256). Code-only deliveries need **no internet**: the project is installed "editable", so the venv runs `project/` directly. If pip can't reach the internet, it retries with the venv's own setuptools (`--no-build-isolation --no-deps`, now part of the `dev` extras) and says what is incomplete. If the venv still can't be updated, `apply` says the delivery **is** applied and to run `./aixun reinstall` later. New: `./aixun reinstall`; `./aixun status` shows whether the venv matches `pyproject.toml` |
| Preferences in the workspace | `aixun/config/gui.json` (passed by `./aixun gui` in `T3X_CONFIG`): last firmware folder, window position/size, the "compare with second address" choice, the update notice. Qt's own file-dialog history (normally `~/.config/QtProject.conf`) is redirected to the same folder; file dialogs use Qt's own dialog (the GTK one records "recent files" in `~/.local/share`) |
| Flash time and speed | Flash page: speed (KB/s), ms per chunk and seconds left, measured from the first acknowledged chunk; before the transfer, the expected time from this product line's earlier flashes in the history (median), else 0.2 s/chunk |
| History import | `t3x-history import [DIR]`, `./aixun history import [DIR]`, and **Import earlier logs** in the History window rebuild records from flash logs (t3x-update, GUI, or the original `t3xupdate_safe.py`): stations before/after, bootloader, chunks, transfer time, port, USB serial. Simulator logs and already-listed logs are skipped. File name and SHA-256 are not in logs, so they stay empty |
| Newer-version notice | Opt-in tick box in **Check online…**. After each probe, the saved/online list is checked in the background; if it lists a newer version for the station's product, the Connect page says so. Nothing is downloaded. Silent when offline |

## 2. Verified, not assumed

| Claim | Evidence |
|---|---|
| Qt writes `~/.config/QtProject.conf` when a file dialog closes | Reproduced with an empty `HOME`: without the redirect the file appears there; with it, it appears in the workspace's `config/` |
| The GUI writes nothing outside the workspace | `test_gui_writes_nothing_outside_the_workspace`: the real entry point runs with an empty `HOME` and `XDG_*` dirs, opens a file dialog, changes folder and size, closes. Afterwards `HOME` is empty (only a fontconfig cache is tolerated) and `config/` holds `gui.json` (+ `QtProject.conf`) |
| Offline `apply` | Copy workspace with the proxy and package index pointed at a dead port and pip's cache off: code-only delivery → "venv already matches pyproject.toml: nothing to install"; delivery with a changed `pyproject.toml` → online install fails, offline re-install succeeds with a warning, `status` reports "NOT in sync"; `./aixun reinstall` online fixes it |
| History import on real logs | The Pi's two 2026-10-11 logs import as `T3BS 1.16 → 1.15 OK 82/82 16.5 s` and `T3BS 1.15 → 1.16 OK 82/82 16.7 s`; the three 21:4x simulator logs are skipped |

## 3. Bug found and fixed

| Symptom | Cause | Fix |
|---|---|---|
| 1 crash (segmentation fault) in 4 full test runs, in the update-notice test | The background job's result was connected to a plain Python closure. PySide6 runs such a slot in the **worker** thread, which then touched widgets. Demonstrated: a closure slot ran in thread `Dummy-1`, a bound method of a widget in `MainThread` | Results go to a method of the window (delivered on the GUI thread). `OnlineDialog._run` now asserts that its slot is a QObject method. 12/12 repeated runs and two full runs clean |

## 4. Tests added (8)

`tests/test_session04.py` (6): config round-trip and bad files; nothing written outside the workspace (subprocess, empty HOME); saved firmware folder used next time; history import from an anonymised real log (`tests/data/`); history CLI; Flash page estimate from history and live speed. `tests/test_online.py` (+2): update notice on/off (off makes no request at all).

## 5. Open

| ID | Item |
|---|---|
| L20 | **Closed** (offline apply), effective from the **next** delivery: `apply` runs the script already in `main`, so applying 04 itself still uses 03a's script (needs the internet once) |
| L21 | Earlier GUI sessions on the Pi may already have created `~/.config/QtProject.conf` (file-dialog history only). Harmless; can be deleted |
