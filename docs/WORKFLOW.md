# Workflow: a self-contained workspace for receiving, testing and accepting deliveries

Everything (code, Python environment, firmware, results, incoming deliveries)
lives in **one folder** that you can put anywhere. Nothing is configured
system-wide: no shell-profile edits, no global git settings, no system `pip`.
One script, `aixun`, does every step, and every path is worked out from the
script's own location. Anyone can rebuild the same setup with two commands.

---

## 1. The workspace

```
aixun/                      ← the workspace root: any location you choose ($WS below)
├── aixun                   ← shortcut to project/tools/aixun.sh (created by setup)
├── project/                ← the code: a git repository; deliveries replace its contents
├── venv/                   ← private Python environment; deliveries never touch it
├── firmware/               ← vendor .bin images (never committed, never shared)
├── results/                ← test output, probe reports, flash logs, history.jsonl, online/ (saved version list)
├── config/                 ← GUI preferences (gui.json) and Qt's own settings; created on first use
└── deliveries/             ← incoming .zip files, kept as history
```

| Concept | What it is | Why it is here |
|---|---|---|
| **git repository** (`project/`) | The code plus its history (`project/.git/`) | Every delivery is a commit you can inspect and undo |
| **branch** | A separate line of commits | `main` = last accepted version; `delivery/<name>` = the delivery under test |
| **venv** (`venv/`) | A private Python installation | Kali blocks system-wide `pip`; the venv is disposable and only serves this workspace |
| **editable install** | The venv points at `project/` instead of copying it | New code is used immediately; the script re-installs when needed |
| **pytest** | Test runner | Proves a delivery works on *your* machine before the station is involved |

---

## 2. Before you start: what you need

| # | Item | Needed for | Where to get it |
|---|---|---|---|
| 1 | System packages: `git rsync unzip python3-venv python3-full` | Everything | `apt` (below) |
| 2 | Membership of the `dialout` group | Talking to the station (`probe`, `flash`) | `usermod` (below) |
| 3 | A **delivery zip** (e.g. `t3x_session01c.zip`) | Creating the workspace | Sent with each delivery |
| 4 | **Firmware images** for your station's product line (see the next table) | `probe`, `flash`, and the real-image test. **Not** needed for `setup`, nor for `test`, which then skips that one test | <https://aixun-updates.github.io/> |
| 5 | The station, its USB data cable (no hub) | `probe`, `flash`, `gui` (except `gui --sim`) | n/a |
| 6 | For the GUI only: a graphical desktop session (not SSH), the Qt libraries `libxcb-cursor0 libxkbcommon-x11-0 libegl1`, and glibc 2.39 or newer | `gui` | `apt` (below); glibc comes with the OS: `ldd --version` shows it |

**Which firmware images, and why:**

| File | Role | Required? |
|---|---|---|
| `JC_M_<PRODUCT>_<target>.bin`, e.g. `JC_M_T3BS_1.16.bin` | The version you want on the station; used by `probe` (compatibility check) and `flash` | Yes, for `probe` / `flash` |
| `JC_M_<PRODUCT>_<current>.bin`, e.g. `JC_M_T3BS_1.06.bin` | Your rollback image: the station's firmware cannot be read back, so this file is the only copy of what you are replacing | Strongly recommended before any flash |
| `JC_M_T3B_1.16.bin` **and** `JC_M_T3BS_1.16.bin` | Used together by the real-image test (checks CRCs and the T3B/T3BS differences) | Optional |

`<PRODUCT>` is whatever your station reports (`./aixun probe` shows it as `Product (field2)`), not what the sticker says.
Versions don't have to be the newest: use the version you intend to install.

### 2.1 System prerequisites (once per machine)

These are the only system-level steps. They install standard tools and grant serial-port access; they don't configure the project.

```bash
sudo apt update
sudo apt install -y git rsync unzip python3-venv python3-full
# git           version control          rsync   copies deliveries into project/
# unzip         unpacks deliveries        python3-venv / python3-full   lets Python create a venv

sudo usermod -aG dialout "$(id -un)"
# lets your user open /dev/ttyUSB* (the station) without sudo
# log out and back in once for this to take effect; 'id -nG' should then list 'dialout'

sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1
# only for the GUI: libraries Qt needs to open a window (X11 cursor, keyboard map, OpenGL/EGL)
# without them the GUI stops with "could not load the Qt platform plugin xcb"

ldd --version | head -n1
# only for the GUI: prints the glibc version; it must be 2.39 or newer for the PySide6 6.12 download
```

`./aixun setup` checks all of this and tells you exactly what's missing.

---

## 3. Create the workspace

### 3.0 Starting over (only if you tried before)

A workspace is just a folder, so starting over means deleting it. Do this **only** if you want to
throw away an earlier attempt; keep your firmware files first.

```bash
cp -a /path/of/old/aixun/firmware ~/aixun-firmware-backup   # save your .bin files (skip if there are none)
rm -rf /path/of/old/aixun                                   # deletes the old workspace, its venv and its results
```

Old virtual environments made elsewhere (for example a `venv/` you created by hand in another
folder) do not interfere: each venv is isolated and this workspace only ever uses its own
`venv/`. You can delete them whenever you like; it is not required.

Choose **any** location for the workspace and set it once per terminal (nothing is saved system-wide):

```bash
WS=/path/of/your/choice/aixun          # e.g. WS=~/Documents/Scripts/aixun
```

### 3a. From a delivery zip

```bash
mkdir -p "$WS/deliveries"                            # the workspace root and its inbox
cd "$WS"                                             # every command below runs from here
mv /path/to/t3x_session01c.zip deliveries/           # file the delivery in the inbox

unzip -q deliveries/t3x_session01c.zip -d .          # creates ./project (the zip's top folder is 'project')
./project/tools/aixun.sh setup
# 1/5 checks prerequisites and the folder layout
# 2/5 creates firmware/ results/ deliveries/
# 3/5 makes project/ a git repository with a first "Baseline" commit
# 4/5 creates venv/
# 5/5 installs the project and its dependencies into venv/ (pip shows its progress; a few
#     minutes on a Raspberry Pi), then creates the ./aixun shortcut and prints a summary
```

> **Layout check.** `setup` expects the code at `<workspace>/project/`. Deliveries up to
> 01b had a top folder called `aixun_t3x_safe_updater_and_probe`; if it ends up *inside*
> `project/`, setup now warns and asks before continuing, because the workspace root would
> otherwise silently become `project/` itself.

### 3b. From GitHub

```bash
mkdir -p "$WS" && cd "$WS"
git clone https://github.com/dzalf/aixun-t3x-safe-flasher.git project
./project/tools/aixun.sh setup
```

Full instructions for every distribution: [INSTALLATION.md](../INSTALLATION.md). Contributors: [CONTRIBUTING.md](../CONTRIBUTING.md).
The script works with `main` or `master` as the base branch.

### 3c. Put your firmware in place

```bash
cp /path/to/JC_M_T3BS_1.16.bin /path/to/JC_M_T3BS_1.06.bin firmware/
# firmware/ sits outside project/: a delivery can never delete these files, and git never sees them
./aixun run t3x-image scan firmware                 # confirm each image is listed as OK
```

---

## 4. Daily commands

All run from the workspace root. **No venv activation is needed**: the script uses `venv/` directly, whatever shell you use.

| Command | What it does |
|---|---|
| `./aixun help` | List the commands |
| `./aixun status` | Current branch, last commits, Python version, where pyserial is loaded from, file counts |
| `./aixun test` | Full test suite; real-firmware tests use `firmware/` automatically; output saved to `results/pytest_<branch>_<commit>_<time>.txt` |
| `./aixun test tests/test_probe.py` | Any pytest arguments pass through (one file, `-x`, `-k name`, …) |
| `./aixun probe JC_M_T3BS_1.16.bin` | **Station needed, read-only.** Probe + image check + 50× reader test; saves `results/probe_<time>.txt` and `.json` |
| `./aixun flash JC_M_T3BS_1.16.bin` | **Station needed, writes firmware.** Pre-flight summary, waits for `yes`; log saved in `results/` |
| `./aixun gui` | The graphical updater. Reads images from `firmware/`, writes logs and reports to `results/`. Probing is read-only; it writes only after you tick the confirmation and click **Flash firmware** |
| `./aixun gui --sim` | The same GUI connected to a built-in simulated T3BS 1.06. No station needed; nothing touches USB |
| `./aixun gui --sim --sim-fail-at-chunk 31` | Simulates the cable being pulled at chunk 31 (once, like a real pull), so you can see the failure page, then **Resume / retry** → Recovery → success |
| `./aixun online list --product T3BS` | **Internet, read-only.** Versions listed on aixun-updates.github.io for that product (newest first) |
| `./aixun online compare --product T3BS` | **Internet, read-only.** Are the files in `firmware/` byte-identical to the site's copies of the same versions? |
| `./aixun online get T3BS 1.16` | **Internet.** Download that version (or `latest`) into `firmware/`, check it, save a `.source.json` record next to it. Never overwrites, never flashes |
| `./aixun history` | Every update attempt recorded in `results/history.jsonl` (GUI and `flash`) |
| `./aixun history import` | Add flash logs made before the history existed (from `results/`, or `./aixun history import /some/folder`) |
| `./aixun reinstall` | Re-install the project into `venv/` (after an interrupted `apply`, or if `status` says "NOT in sync") |
| `./aixun run t3x-image scan firmware` | Run any project command inside the venv |
| `./aixun sim` | Simulated station for development (see §8) |

File names given to `probe` and `flash` are looked up in `firmware/` first.

---

## 5. Receiving a delivery

```bash
cd "$WS"
mv /path/to/t3x_session02.zip deliveries/     # file it in the inbox (optional: apply also copies it there)
./aixun apply t3x_session02.zip
# 1. refuses to run if project/ has uncommitted edits (so nothing of yours is lost)
# 2. creates branch delivery/t3x_session02 from main
# 3. unpacks the zip to a temporary folder and mirrors it into project/
#    (rsync --delete: removed files are removed, project/.git is never touched)
# 4. commits the result and prints which files changed
# 5. updates the venv ONLY if pyproject.toml changed (new dependencies or commands); a code-only
#    delivery needs no internet. If the update can't finish (offline), the delivery is still applied:
#    run './aixun reinstall' when online, then './aixun test'

./aixun test                                   # always test before accepting
```

## 6. Accept or roll back

```bash
./aixun accept      # merge delivery/<name> into main; it becomes the new baseline
./aixun rollback    # asks for confirmation, returns to main, deletes the delivery branch
```

The venv stays valid either way; `rollback` re-installs main's dependencies.

---

## 7. What to send back

| Situation | Send |
|---|---|
| After `./aixun test` | The `results/pytest_*.txt` file it names (the last 20 lines if everything passed) |
| After `./aixun probe` | `results/probe_*.json` |
| After `./aixun flash` | `results/t3x_flash_*.log`. It contains your station's USB serial number, so don't post it publicly |
| After using the GUI | The `results/t3x_report_*.json` from **Export report…** and the `results/t3x_flash_*.log` it names (same privacy note) |
| Always | The output of `./aixun status` (it identifies the exact version tested) |

---

## 8. Developing without the station

```bash
./aixun sim                                    # terminal 1: simulated T3BS v1.06 (Ctrl-C to stop)
./aixun sim --fail-at-chunk 31                 # ...or one that "loses USB" at chunk 31 (first transfer only)
```

Everything produced against the simulator goes to `results/sim/` (logs, history), so it can never be
mistaken for your real station's records. The Recovery page and `flash` ignore simulator logs.

```bash
export T3X_SIM_PORTS="$WS/results/.sim-ports.json"     # terminal 2: point the tools at the simulator
./aixun probe JC_M_T3BS_1.16.bin
./aixun flash JC_M_T3BS_1.16.bin
unset T3X_SIM_PORTS                                    # back to the real station
```

The GUI has the simulator built in, so it needs only one terminal:

```bash
./aixun gui --sim                       # simulated T3BS 1.06, normal flow
./aixun gui --sim --sim-bootloader      # station already stuck in its bootloader: opens the Recovery page
./aixun gui --sim --sim-product T3B     # a T3B station: T3BS images are shown as incompatible
```

---

## 8a. Firmware from aixun-updates.github.io

| What | Where it really comes from |
|---|---|
| The page you browse | `https://aixun-updates.github.io/` (GitHub Pages, a static page; unofficial changelog) |
| The version list it shows | `<data host>/files/changelog.json`. The data host is named in the page's own `assets/js/config.js`; in October 2026: `https://usr.tnyzeq.icu/~dd/aixun-updates` |
| The **Download** link on the page | `<data host>/firmware/<file name>`. A `.bin` downloaded "from aixun-updates.github.io" comes from here |
| A second address per file | The version list also records a `url` on `aixun-file.oss-cn-shenzhen.aliyuncs.com` (plain http). The page doesn't show it; the name suggests AiXun's own storage, but that is **not confirmed** |

`./aixun online` and **Check online…** in the GUI read `config.js` every time, so they always download from
wherever the page itself links. With comparison on (default), the second address is used **only** to check
that both serve identical bytes: if they differ, nothing is saved. No checksums are published by the site;
each saved file gets `<file>.source.json` with its SHA-256, both addresses and the comparison result.

The version list (~650 KB) is kept in `results/online/` and re-checked cheaply on the next run; it is
also shown when you're offline (with a note). Add `--refresh` to read it again, `-v` to see what each
request cost (size, time, IPv4/IPv6), e.g. `./aixun online list --product T3BS -v`.

---

## 9. Moving, copying or sharing the workspace

| Action | What to do |
|---|---|
| Move or rename `aixun/` | Everything follows except `venv/` (Python environments store absolute paths). Run `./aixun rebuild-venv` once |
| Copy to another machine | Copy the folder **without** `venv/`, then run `./project/tools/aixun.sh setup` there |
| Give it to someone else | Share only `project/` (the repository, or a zip of it). They follow §3 |
| Python upgraded by Kali | `./aixun rebuild-venv` |

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `setup` says something is missing | Run the `apt install` line it prints |
| Warning: not in the `dialout` group | `sudo usermod -aG dialout "$(id -un)"`, then log out and back in |
| `apply`: "project has uncommitted changes" | `./aixun status` shows them; discard with `git -C project restore .` or keep with `git -C project stash` |
| `apply`: "branch already exists" | Finish the previous delivery first: `./aixun accept` or `./aixun rollback` |
| `status` shows pyserial outside `venv/` | `./aixun rebuild-venv` |
| `./aixun: No such file or directory` | You're not in the workspace root, or setup hasn't run: `cd "$WS"`, then `./project/tools/aixun.sh setup` |
| GUI: "could not load the Qt platform plugin xcb" | `sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1` |
| GUI: "no desktop session found" / nothing appears | Run it from a terminal **inside** the desktop session, not over SSH |
| GUI: "the GUI is not installed" | PySide6 failed to install during `apply`; scroll back for pip's error (usually glibc older than 2.39) |
| GUI: "not answering yet" or "port busy" right after plugging the station in | Normal for the first seconds: the GUI waits 1.5 s, then retries for up to 30 s by itself. If it never gets an answer: check the station is switched on; unplug, wait 5 s, plug in again. To see whether **ModemManager** (a service that tests new serial ports for modems) is involved: `systemctl is-active ModemManager` (prints `active` or `inactive`), then right after plugging in: `journalctl -b -u ModemManager --since "-2 min" \| grep -i tty` (any `ttyUSB` lines mean it opened the station's port). Only if it does, and only if you want a system-wide change, it can be told to ignore the station: see the note below this table |
| Station not listed | Direct USB-A → USB-C data cable, no hub; check with `./aixun run python -m serial.tools.list_ports -v` |


> **Optional, system-wide: tell ModemManager to ignore the station.** This is the only step in
> this document that changes system configuration, so it is opt-in and not needed for the GUI
> to work. It creates one udev rule file that matches only the AiXun's USB serial number prefix:
>
> ```bash
> echo 'ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="JCID_*", ENV{ID_MM_DEVICE_IGNORE}="1"' \
>   | sudo tee /etc/udev/rules.d/99-aixun-t3x.rules        # write the rule (needs sudo)
> sudo udevadm control --reload-rules                       # load it; takes effect at the next plug-in
> # to undo: sudo rm /etc/udev/rules.d/99-aixun-t3x.rules && sudo udevadm control --reload-rules
> ```

---

## 11. Under the hood (for learning, and for reuse in other projects)

| `./aixun …` | Equivalent manual commands |
|---|---|
| `setup` | `mkdir firmware results deliveries` · `git -C project init -b main` · `git -C project add -A && git -C project commit -m Baseline` · `python3 -m venv venv` · `venv/bin/pip install -e "project[dev]"` · `ln -s project/tools/aixun.sh aixun` |
| `apply Z` | `git -C project switch -c delivery/Z main` · `unzip Z -d /tmp/x` · `rsync -a --delete --exclude .git /tmp/x/*/ project/` · `git -C project add -A && git -C project commit` · `venv/bin/pip install -e "project[dev]"` |
| `test` | `cd project && T3X_FW_DIR=../firmware ../venv/bin/pytest -v -rs \| tee ../results/…` |
| `accept` | `git -C project switch main && git -C project merge --no-ff delivery/Z && git -C project branch -d delivery/Z` |
| `rollback` | `git -C project switch main && git -C project branch -D delivery/Z` |

**To reuse the pattern elsewhere:** copy `tools/aixun.sh` into another project, rename it, and change the commands that are specific to this project (`probe`, `flash`, `sim`). The workspace layout, `setup`, `apply`, `test`, `accept`, `rollback`, `status`, `run` and `rebuild-venv` work for any Python project with a `pyproject.toml`.
