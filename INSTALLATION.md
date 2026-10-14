# Installation: from scratch, on any Linux distribution

This guide sets up the **complete development and usage environment**: the code, a private
Python environment, folders for firmware and results, and the `./aixun` command that runs
everything. Every command is commented. Nothing is configured system-wide except the
system packages (step 1) and serial-port access (step 2).

> Commands can be pasted as they are. Lines starting with `#` are comments; the shell ignores them.
>
> **Python developers** who only want the package in a normal virtual environment (no workspace):
> install the system packages of step 1, then follow [CONTRIBUTING.md](CONTRIBUTING.md) §2.

---

## 0. What you will have at the end

```
aixun/                      ← the workspace: any folder you choose (called $WS below)
├── aixun                   ← shortcut to project/tools/aixun.sh (created by setup)
├── project/                ← this repository (git clone)
├── venv/                   ← private Python environment (created by setup, ~280 MB with the GUI)
├── firmware/               ← AiXun .bin images you download (never committed)
├── results/                ← test output, probe reports, flash logs, flash history
├── deliveries/             ← optional: patch archives exchanged as .zip (see CONTRIBUTING.md)
└── config/                 ← GUI preferences (created when the GUI first saves them)
```

Only `project/` is in git. Everything else is created on your machine by `./aixun setup`
or by using the tools, and stays out of the repository (see `.gitignore`).

### Where this has been tested

| Platform | What was tested | Result |
|---|---|---|
| Raspberry Pi 5, **Kali Linux** (aarch64), Python 3.14.7 | Full setup, all tests, GUI, read-only probes, **real flashes** of a T3BS (1.06 → 1.16, 1.16 → 1.15 → 1.16, twice) | ✅ |
| **Ubuntu 24.04** (x86_64), Python 3.13 | Fresh `git clone` + `setup` in a folder with a space in its name, all tests, GUI rendered headless | ✅ (no station attached) |
| Debian, Raspberry Pi OS, Linux Mint, Pop!_OS | Same package names as Ubuntu/Kali | Expected to work, **not tested** |
| Fedora, openSUSE, Arch/Manjaro | Package names below come from those distributions' naming; the `./aixun` script detects `dnf`, `zypper` and `pacman` | Expected to work, **not tested** |
| Windows, macOS | Not supported (see README) | ✗ |

If you try an untested distribution, please report the result (see CONTRIBUTING.md).

---

## 1. Requirements

| Item | Needed for | Notes |
|---|---|---|
| Linux with `bash`, `git`, `rsync`, `unzip`, `sha256sum` | Everything | `sha256sum` is part of coreutils, present everywhere |
| Python **3.9 or newer** with the `venv` module | Command-line tools | `python3 --version` |
| Python **3.10 or newer** | The GUI | PySide6 6.x wheels need 3.10+ |
| glibc **2.39+** (aarch64) or **2.34+** (x86_64) | The newest PySide6 (6.12) | `ldd --version`. On older systems pip picks an older PySide6 if one fits |
| Qt runtime libraries (`libxcb-cursor`, `libxkbcommon-x11`, `libEGL`) | The GUI | Step 1 |
| A graphical desktop session (X11 or Wayland) | The GUI | Not over plain SSH |
| Internet access | Setup (Python packages), the optional online firmware list | Afterwards, code-only updates work offline |
| ~400 MB free disk space | venv (~280 MB) + code + firmware | |
| Membership of the serial-port group | Talking to the station | Step 2 |
| An AiXun T3x station and a USB **data** cable, no hub | Probing and flashing only | Not needed for development: there is a simulator |

---

## 2. Step 1: system packages (once per machine)

Pick **your** distribution family. These are the only system-wide installs.

### Debian, Ubuntu, Kali, Raspberry Pi OS, Linux Mint, Pop!_OS (apt)

```bash
sudo apt update
# refresh the package lists

sudo apt install -y git rsync unzip python3 python3-venv
# git: version control · rsync/unzip: used by ./aixun · python3-venv: lets Python create the private environment

sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1
# only for the GUI: X11 cursor, keyboard and OpenGL/EGL libraries that Qt needs to open a window
```

### Fedora, RHEL, AlmaLinux, Rocky (dnf)

```bash
sudo dnf install -y git rsync unzip python3
# Fedora's python3 already includes the venv module

sudo dnf install -y xcb-util-cursor libxkbcommon-x11 mesa-libEGL
# only for the GUI. On RHEL-compatible systems xcb-util-cursor may need the EPEL repository:
#   sudo dnf install -y epel-release
```

### openSUSE (zypper)

```bash
sudo zypper install -y git rsync unzip python3
# if 'python3 -m venv' later fails, also: sudo zypper install -y python3-pip

sudo zypper install -y libxcb-cursor0 libxkbcommon-x11-0 libEGL1
# only for the GUI
```

### Arch Linux, Manjaro, EndeavourOS (pacman)

```bash
sudo pacman -S --needed git rsync unzip python
# Arch's python includes the venv module

sudo pacman -S --needed xcb-util-cursor libxkbcommon-x11 libglvnd
# only for the GUI
```

### Check

```bash
python3 --version
# must print 3.9 or newer (3.10+ for the GUI)

python3 -c "import venv, ensurepip; print('venv OK')"
# must print: venv OK

ldd --version | head -n1
# glibc version (see the requirements table)
```

---

## 3. Step 2: permission to use the serial port (once per user)

USB serial devices (`/dev/ttyUSB*`) belong to a group. Find its name and join it:

```bash
ls -l /dev/ttyUSB* 2>/dev/null || echo "no station plugged in: use the table below"
# with the station plugged in, the group is the 4th column, e.g. 'dialout' or 'uucp'
```

| Distribution | Group |
|---|---|
| Debian, Ubuntu, Kali, Raspberry Pi OS, Mint, Fedora, openSUSE | `dialout` |
| Arch, Manjaro | `uucp` |

```bash
sudo usermod -aG dialout "$(id -un)"
# add yourself to the group (replace dialout with uucp on Arch/Manjaro)

# Log out and log back in (or reboot) so the new membership takes effect, then:
id -nG
# the list must now contain dialout (or uucp)
```

---

## 4. Step 3: create the workspace and get the code

Choose **any** folder for the workspace. Set it once per terminal; nothing is saved system-wide.

```bash
WS="$HOME/aixun"
# example location; any path works, including one with spaces (keep the quotes)

mkdir -p "$WS"
# create the workspace folder

cd "$WS"
# every command from here on runs inside the workspace

git clone https://github.com/dzalf/aixun-t3x-safe-flasher.git project
# the repository MUST be cloned into a folder called 'project' inside the workspace
```

If you will contribute changes, clone **your fork** instead (see CONTRIBUTING.md), for example
`git clone https://github.com/<your-user>/aixun-t3x-safe-flasher.git project`.

---

## 5. Step 4: set up the environment

```bash
./project/tools/aixun.sh setup
# 1/5 checks the prerequisites and the folder layout (tells you the exact install command if
#     something is missing)
# 2/5 creates firmware/ results/ deliveries/
# 3/5 keeps the git repository you cloned
# 4/5 creates venv/ (a private Python; your system Python is not touched)
# 5/5 installs the project and its dependencies into venv/ with visible progress: pyserial,
#     pytest, setuptools and, for the GUI, PySide6 (~85 MB download; several minutes on a Pi).
#     Then creates the ./aixun shortcut and prints a summary.

./aixun status
# branch, latest commits, Python version, whether venv/ matches pyproject.toml, file counts
```

**No activation needed.** `./aixun` uses `venv/` directly; you never run `source venv/bin/activate`.

### Optional: the exact versions of the reference environment

`constraints/tested.txt` lists the package versions used on the reference Raspberry Pi. To use
exactly those (only on systems that meet the glibc requirement above):

```bash
AIXUN_CONSTRAINTS="$WS/project/constraints/tested.txt" ./aixun reinstall
# reinstalls the project into venv/ with those pinned versions
```

---

## 6. Step 5: verify the installation (no station needed)

```bash
./aixun test
# runs the full test suite against a simulated station; output also saved in results/
# expected: "103 passed, 1 skipped" (the skipped test needs the real firmware files of step 6;
#           with JC_M_T3B_1.16.bin and JC_M_T3BS_1.16.bin in firmware/ it becomes 104 passed)
# takes about 4–5 minutes on a Raspberry Pi 5

./aixun gui --sim
# opens the GUI connected to a built-in simulated T3BS 1.06: go through Connect → Verify →
# Flash → Done without any hardware. Close the window when finished.
```

If the GUI doesn't open, see Troubleshooting (section 11).

---

## 7. Step 6: firmware images

Firmware is **never** included in the repository. Download it into `firmware/`:

```bash
./aixun online list --product T3BS
# versions listed on aixun-updates.github.io for that product (use your station's product:
# the probe in step 8 shows it; a T3B-labelled station may report T3BS)

./aixun online get T3BS 1.16
# downloads JC_M_T3BS_1.16.bin into firmware/, checks it (header, size, CRC, vector table,
# product, version), compares it with the second address the site records, and saves a
# .source.json record next to it. Never overwrites, never flashes.

./aixun online compare --product T3BS
# confirms the files in firmware/ are byte-identical to the site's copies
```

Manual alternative: download the `.bin` from <https://aixun-updates.github.io/> and copy it into
`firmware/`, then check it with `./aixun run t3x-image info firmware/JC_M_T3BS_1.16.bin`.
Where those files really come from is explained in `docs/WORKFLOW.md` §8a.

Keep a copy of the version currently on your station as a rollback image: the station's
firmware cannot be read back.

---

## 8. Step 7: connect the station (read-only first)

```bash
./aixun run python -m serial.tools.list_ports -v
# the station appears as /dev/ttyUSB0 (or ttyUSB1…) with hwid VID:PID=0403:6001 SER=JCID_…
# on a Raspberry Pi, /dev/ttyAMA* is the Pi's own UART: ignore it

./aixun probe JC_M_T3BS_1.16.bin
# READ-ONLY: identity, version, link test (100 queries) and image compatibility. It cannot
# enter the bootloader. Saves results/probe_<time>.txt and .json

./aixun gui
# the graphical updater: it probes automatically (read-only); it writes firmware only after
# you tick the confirmation box and click "Flash firmware"
```

Before a flash, read the safety notes in the README. While flashing: don't unplug, don't power
off. If something fails, the station stays in its bootloader and the GUI's Recovery page
completes the update.

### Optional: ModemManager

On many desktops a service called ModemManager briefly opens new serial ports. The station
re-appears on USB twice during an update. The GUI shows a note when ModemManager is running.

```bash
systemctl is-active ModemManager
# 'active' or 'inactive' (read-only)

sudo systemctl stop ModemManager
# optional, before flashing; it comes back at the next reboot, or with:
sudo systemctl start ModemManager
```

A permanent, opt-in udev rule that only tells ModemManager to ignore the station is in
`docs/WORKFLOW.md` §10.

---

## 9. Updating

```bash
git -C project pull
# fetch the latest code from GitHub (into project/)

./aixun status
# if it says "NOT in sync with pyproject.toml", dependencies changed:
./aixun reinstall
# reinstall into venv/ (needs internet)

./aixun test
# always re-test after an update
```

After a Python upgrade by your distribution, or after moving/renaming the workspace folder:

```bash
./aixun rebuild-venv
# deletes and recreates venv/ (venvs contain absolute paths and the Python version)
```

---

## 10. Uninstalling

```bash
rm -rf "$WS"
# the workspace is self-contained: this removes code, venv, firmware, results and settings.
# Copy firmware/ and results/ elsewhere first if you want to keep them.

sudo gpasswd -d "$(id -un)" dialout
# optional: leave the serial group again (uucp on Arch)

sudo rm -f /etc/udev/rules.d/99-aixun-t3x.rules && sudo udevadm control --reload-rules
# only if you added the optional ModemManager rule
```

System packages from step 1 are ordinary distribution packages; remove them with your package
manager only if nothing else uses them.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `setup`: "missing: …" | A system package is missing | Run the command it prints (it matches your package manager) |
| `setup`: layout warning about `project` | The repository isn't in `<workspace>/project` | Clone into a folder called `project` (step 3) |
| `error: externally-managed-environment` | `pip` was run outside the venv | Use `./aixun …` or `venv/bin/python -m pip …`, never the system `pip` |
| Name resolution / connection errors during setup | No internet or DNS | Fix the network; then `./aixun reinstall` |
| Warning about glibc during setup | PySide6 6.12 has no wheel for your system | pip installs an older PySide6 if possible; the CLI works regardless |
| GUI: "could not load the Qt platform plugin xcb" | Qt libraries missing | Install the GUI packages of step 1 |
| GUI: "No desktop session found" | Started over SSH or without a display | Start it from a terminal inside the desktop |
| GUI on Wayland looks wrong or won't start | Qt platform selection | Try `QT_QPA_PLATFORM=xcb ./aixun gui` (needs Xwayland) |
| `Permission denied: '/dev/ttyUSB0'` | Not in the serial group, or not logged out/in | Step 2, then log out and back in |
| Station not listed | Charge-only cable, hub, or station off | Direct USB data cable, no hub; `dmesg | tail` should show "FTDI USB Serial Device converter now attached to ttyUSB0" |
| Port appears, then disappears right away (Ubuntu and derivatives) | The braille-display service `brltty` can claim some USB-serial adapters | Check `journalctl -k | grep -i brltty`; if it mentions the device: `sudo apt remove brltty` (only if you don't use a braille display) |
| "not answering yet" / "port busy" right after plugging in | Station or ModemManager still starting | The GUI retries for 30 s on its own (section 8 for ModemManager) |
| `./aixun test` fails | Report it | Send the `results/pytest_*.txt` it names (CONTRIBUTING.md) |

---

## 12. Without `./aixun` (manual, for experienced users)

`./aixun` only automates standard steps. The same by hand, inside the cloned repository:

```bash
python3 -m venv venv
# private environment next to the code

venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -e ".[dev,gui]"
# editable install: the venv runs the code in this folder; 'gui' adds PySide6, 'dev' adds pytest

venv/bin/python -m pytest -v
# tests (set T3X_FW_DIR=/path/to/firmware for the real-image test)

venv/bin/t3x-gui --sim
# GUI with the simulator; without --sim it uses ./firmware and ./results of the current folder
```

The workspace layout, delivery branches and `check-publish` are only available through `./aixun`.
