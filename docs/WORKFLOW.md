# The `./aixun` workspace: reference

`./aixun` (the script `tools/aixun.sh`) keeps the code, its Python environment, firmware, results and
settings in **one folder**, and runs every task from there. It's optional: the project is an ordinary
Python package (CONTRIBUTING.md §2). Installation, step by step: [INSTALLATION.md](../INSTALLATION.md).

Every command below runs in the **workspace folder**, the folder that contains `./aixun` and `project/`.
No virtual-environment activation is needed: the script uses `venv/` directly.

---

## 1. The workspace

```text
aixun/                      the workspace: any folder you choose
├── aixun                   shortcut to project/tools/aixun.sh (created by setup)
├── project/                the code: a git repository (this project)
├── venv/                   private Python environment; only this workspace uses it
├── firmware/               firmware images (.bin); never committed
├── results/                test output, probe reports, flash logs, history.jsonl, online/ (saved version list), sim/
├── config/                 GUI preferences and Qt's own settings; created on first use
└── deliveries/             zip snapshots applied with ./aixun apply (section 3)
```

Only `project/` is in git. `firmware/`, `results/` and the rest sit next to it, so nothing in them can be
committed, and applying a snapshot can never delete them.

---

## 2. Commands

| Command | What it does |
|---|---|
| `./aixun help` | List the commands |
| `./aixun setup` | First-time setup (INSTALLATION.md §5) |
| `./aixun status` | Branch, last commits, Python version, where pyserial is loaded from, whether `venv/` matches `pyproject.toml` |
| `./aixun test` | Full test suite; real-firmware tests use `firmware/`; output saved to `results/pytest_<branch>_<commit>_<time>.txt` |
| `./aixun test tests/test_probe.py -x` | Any pytest arguments pass through |
| `./aixun probe FILE.bin` | **Station, read-only.** Probe + image check + reader test; saves `results/probe_<time>.txt` and `.json` |
| `./aixun flash FILE.bin` | **Station, writes firmware.** Pre-flight summary, waits for `yes`; log in `results/` |
| `./aixun gui` | The graphical updater. Writes firmware only after you tick the confirmation and click **Flash firmware** |
| `./aixun gui --sim` | The GUI with a built-in simulated station (section 4) |
| `./aixun online list --product T3BS` | **Internet, read-only.** Versions listed on aixun-updates.github.io, newest first. `--refresh` re-reads the list, `-v` shows request timings |
| `./aixun online compare --product T3BS` | **Internet, read-only.** Are the files in `firmware/` byte-identical to the site's copies? |
| `./aixun online get T3BS 1.16` | **Internet.** Download that version (or `latest`) into `firmware/`, check it, save a `.source.json` record. Never overwrites, never flashes |
| `./aixun history` | Every update attempt (`results/history.jsonl`) |
| `./aixun history import` | Add flash logs made before the history existed (from `results/`, or a folder you name) |
| `./aixun apply ZIP` · `accept` · `rollback` | Snapshots (section 3) |
| `./aixun reinstall` | Re-install the project into `venv/` (after `git pull`, or when `status` says "NOT in sync") |
| `./aixun rebuild-venv` | Delete and recreate `venv/` (after moving the workspace or a Python upgrade) |
| `./aixun check-publish` | Scan the repository and its history for firmware, logs, serial numbers, keys and tokens before pushing |
| `./aixun run COMMAND` | Run any project command inside the venv, e.g. `./aixun run t3x-image scan firmware` |
| `./aixun sim` | Simulated station for the command-line tools (section 4) |

File names given to `probe` and `flash` are looked up in `firmware/` first.

---

## 3. Snapshots: `apply`, `accept`, `rollback`

A **snapshot** is a zip of the project folder: every file git tracks, inside a top folder called
`project/`. This project's development sessions arrived this way (README, "How this project is
developed"); the zips are named after the session, e.g. `t3x_session05d.zip`, and kept in `deliveries/`.
The commands work for any snapshot. To make one:

```bash
git -C project archive --format=zip --prefix=project/ -o my_change.zip HEAD
```

To test a snapshot and keep or discard it:

```bash
./aixun apply my_change.zip
# 1. refuses to run if project/ has uncommitted edits (nothing of yours is lost)
# 2. copies the zip into deliveries/ and creates the branch delivery/my_change from main
# 3. replaces the contents of project/ with the zip's (project/.git is never touched)
# 4. commits the result ("Delivery: my_change") and lists the changed files
# 5. updates venv/ only if pyproject.toml changed; otherwise no internet is needed

./aixun test
# always test before keeping it

./aixun accept
# keep it: merges the branch into main ("Accept my_change")

./aixun rollback
# or discard it: asks for confirmation, returns to main, deletes the branch
```

Pushing the result to GitHub: [MAINTAINERS.md](MAINTAINERS.md) §4.

---

## 4. Working without the station

The GUI has the simulator built in:

```bash
./aixun gui --sim                          # simulated T3BS 1.06, normal flow
./aixun gui --sim --sim-fail-at-chunk 31   # the cable "pulled" at chunk 31 (once): failure, then Recovery
./aixun gui --sim --sim-bootloader         # station already waiting in its bootloader
./aixun gui --sim --sim-product T3B        # a T3B station: T3BS images shown as incompatible
```

For the command-line tools, use two terminals, both in the workspace folder:

```bash
./aixun sim
# terminal 1: simulated T3BS 1.06 (add --fail-at-chunk 31 for a one-time failure); Ctrl-C stops it

T3X_SIM_PORTS=results/.sim-ports.json ./aixun probe JC_M_T3BS_1.16.bin
T3X_SIM_PORTS=results/.sim-ports.json ./aixun flash JC_M_T3BS_1.16.bin
# terminal 2: T3X_SIM_PORTS=… in front of a command points that one command at the simulator
```

Everything produced against the simulator goes to `results/sim/`, so it can't be mixed up with your real
station's records.

---

## 5. Moving or copying the workspace

| Action | What to do |
|---|---|
| Move or rename the workspace folder | Run `./aixun rebuild-venv` once (Python environments store absolute paths) |
| Copy it to another machine | Copy the folder **without** `venv/`, then run `./project/tools/aixun.sh setup` there |
| Python upgraded by your distribution | `./aixun rebuild-venv` |

---

## 6. Troubleshooting (workspace)

Installation, GUI and station problems: INSTALLATION.md §11.

| Symptom | Fix |
|---|---|
| `./aixun: No such file or directory` | You're not in the workspace folder, or setup hasn't run: `./project/tools/aixun.sh setup` |
| `apply`: "project has uncommitted changes" | `./aixun status` shows them; discard with `git -C project restore .`, or keep them with `git -C project stash` |
| `apply`: "branch already exists" | Finish the previous snapshot first: `./aixun accept` or `./aixun rollback` |
| `status` shows pyserial outside `venv/` | `./aixun rebuild-venv` |
| GUI: "the GUI is not installed" | PySide6 failed to install; scroll back for pip's error (usually a glibc that is too old) |

---

## 7. Under the hood

`./aixun` only automates standard commands:

| `./aixun …` | Equivalent manual commands (in the workspace folder) |
|---|---|
| `setup` | `mkdir firmware results deliveries` · `python3 -m venv venv` · `venv/bin/pip install -e "project[dev,gui]"` · `ln -s project/tools/aixun.sh aixun` |
| `apply Z` | `git -C project switch -c delivery/Z main` · `unzip Z -d /tmp/x` · `rsync -a --delete --exclude .git /tmp/x/project/ project/` · `git -C project add -A && git -C project commit -m "Delivery: Z"` |
| `test` | `cd project && T3X_FW_DIR=../firmware ../venv/bin/pytest -v -rs` |
| `accept` | `git -C project switch main && git -C project merge --no-ff delivery/Z && git -C project branch -d delivery/Z` |
| `rollback` | `git -C project switch main && git -C project branch -D delivery/Z` |

To reuse the pattern in another Python project, copy `tools/aixun.sh` and change the project-specific
commands (`probe`, `flash`, `sim`, `online`, `history`); the rest works for any project with a
`pyproject.toml`.
