# Session 01b: Self-contained workspace and delivery workflow

| | |
|---|---|
| Date | 2026-10-11 |
| Trigger | Requirement: no system-wide configuration; everything in one portable folder; a process others can replicate |
| Outcome | `tools/aixun.sh` workspace manager + rewritten `docs/WORKFLOW.md`; full dry run passed |
| Code changes to the updater | None. Simulator: one ordering fix (§4). 49 tests pass |

## 1. Requirements → design

| Requirement | Design |
|---|---|
| Nothing system-wide | No shell-profile edits, git identity set per repository, venv inside the workspace, no system `pip`. Only the apt prerequisites and the `dialout` group remain system-level, and they are unavoidable |
| One folder, organised subfolders | `aixun/{project,venv,firmware,results,deliveries}` plus an `aixun` shortcut |
| Portable / replicable | Every path is derived from the script's own location (`readlink -f`), so the folder can live anywhere. Others: clone or unzip into `project/`, run `setup` |
| Learnable | Every command is documented, with its manual equivalent (WORKFLOW §11) |
| Shell-independent | Bash script with a shebang, run as `./aixun`, so it works from zsh (Kali's default) or bash; no venv activation needed |

## 2. Decisions

| ID | Decision | Rationale |
|---|---|---|
| D11 | The script lives **in the repository** (`tools/aixun.sh`), symlinked to the workspace root | It evolves with the code and is versioned with it, and a rollback restores the matching script |
| D12 | `venv/`, `firmware/`, `results/` and `deliveries/` live **outside** `project/` | Deliveries are mirrored with `rsync --delete` and can never touch user files; git never sees firmware or logs |
| D13 | Deliveries go on `delivery/<zip name>` branches; `accept` uses a `--no-ff` merge | Each delivery is one identifiable merge in `main`'s history |
| D14 | `test` always sets `T3X_FW_DIR=firmware/` | Real-firmware tests run automatically when the images are present |
| D15 | GUI dependencies are installed only once `src/t3x/gui/app.py` exists | No PySide6 download until the GUI is delivered |

## 3. Verification (dry run in a fresh folder)

| Step | Result |
|---|---|
| `setup` with `rsync` missing | Stopped with the exact `apt install` line ✅ |
| `setup` | Folders, git baseline commit, venv, editable install, `./aixun` shortcut; pyserial loaded **from the venv** ✅ |
| `test tests/test_image.py` | 13 passed, 1 skipped (no firmware yet); output saved as `results/pytest_main_<commit>_<time>.txt` ✅ |
| `apply` delivery 02 (one file deleted, two changed) | New branch; diff stat listed all 3; the deleted file was really removed ✅ |
| `test` with firmware present | 14 passed, 0 skipped (real-image test ran) ✅ |
| `accept` | `--no-ff` merge into main; branch removed ✅ |
| `apply` delivery 03, then `rollback` | Back on main; README change gone ✅ |
| `sim` + `probe` + `flash` + `run` | Probe 8/8 PASS with .txt and .json saved; flash successful with its log in `results/`; `t3x-image scan` listed both images ✅ |
| `shellcheck -S warning` | Clean ✅ |

## 4. Bugs found during the dry run

| Bug | Fix |
|---|---|
| `setup` crashed with `USER: unbound variable` in shells where `$USER` is not set (strict mode `set -u`) | Uses `id -un` instead |
| shellcheck: two `local x=$(…)` assignments hid exit codes; `"$PROJECT[dev]"` was ambiguous | Declared separately; `"${PROJECT}[dev]"` |
| **Flaky test** `test_interrupted_transfer_then_recovery` (about 1 failure in 6 full runs): the simulator dropped off USB *before* switching to bootloader mode, so a fast host could read the old mode. Simulator ordering only; the updater was not affected | `SimStation._reenumerate` switches mode first, then detaches. The affected files ran 12× in a row (216 test executions), 0 failures |

## 5. Next

GUI delivery, applied through this workflow (`./aixun apply`, `./aixun test`).
