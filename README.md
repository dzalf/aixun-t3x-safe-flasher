# AiXun T3x safe flasher

Update the firmware of **AiXun T3x soldering stations** (T3B / T3BS and relatives) from
**Linux**, without AiXun's Windows software, with a read-only probe, pre-flight checks,
a recovery path and a graphical updater.

![Pre-flight check page](docs/img/gui_12_verify_s03.png)

> **Disclaimer.** Flashing firmware always carries some risk. This project is not affiliated
> with or endorsed by AiXun/JCID. Use it at your own risk; read the safety notes below.

---

## Status

| | |
|---|---|
| Version | 0.1.0 (see [CHANGELOG.md](CHANGELOG.md)) |
| Tested hardware | A T3B-labelled station that reports **T3BS**: flashed 1.06 → 1.16, and 1.16 → 1.15 → 1.16 twice, from a **Raspberry Pi 5 running Kali Linux** (October 2026) |
| Tested hosts | Raspberry Pi 5 / Kali (aarch64, Python 3.14): everything. Ubuntu 24.04 (x86_64, Python 3.13): setup and all tests, no station |
| Not tested | Other stations (T3A, T320, T420D …), other distributions, recovery from a *real* interrupted transfer (simulated only) |
| Platforms | Linux only. Windows can't be used: the station's USB interface is rejected by current FTDI drivers (see [docs/SCRIPTS_GUIDE.md](docs/SCRIPTS_GUIDE.md) §1) |
| Tests | 104 automated tests against a simulated station, including byte-for-byte comparison with the hardware-proven script |

---

## What it does

| Feature | Details |
|---|---|
| **Read-only probe** | Identity, version, a 100-query link test and image compatibility. It *cannot* enter the bootloader: only two query commands are allowed |
| **Image checks** | Header, size, CRC, vector table, product line and version, before anything is sent. A T3B image is refused for a T3BS station, also in bootloader mode |
| **Guided GUI** | Connect → Verify → Flash → Done, with a chunk map, live speed and time left, a changelog of what changes, downgrade warnings, and an explicit confirmation that resets when you pick another file |
| **Recovery** | If a transfer is interrupted, the station waits in its bootloader; the GUI detects this, shows where the last flash stopped, and completes the update |
| **Firmware online** | Lists the versions published on aixun-updates.github.io, checks your files are byte-identical to the site's copies, downloads with provenance records. Never flashes on its own |
| **History** | Every update attempt recorded locally (`results/history.jsonl`), viewable in the GUI |
| **Simulator** | A complete simulated station for development and demos: `./aixun gui --sim` |
| **Self-contained workspace** | Code, Python environment, firmware, logs and settings in one folder; nothing configured system-wide beyond the packages and the serial group |

---

## Quick start

Full, distribution-specific instructions: **[INSTALLATION.md](INSTALLATION.md)**. In short (Debian/Ubuntu/Kali/Raspberry Pi OS):

```bash
sudo apt install -y git rsync unzip python3 python3-venv libxcb-cursor0 libxkbcommon-x11-0 libegl1
sudo usermod -aG dialout "$(id -un)"          # then log out and back in

mkdir -p ~/aixun && cd ~/aixun                # the workspace: any folder you like
git clone https://github.com/dzalf/aixun-t3x-safe-flasher.git project
./project/tools/aixun.sh setup                # private venv + folders + ./aixun shortcut
./aixun test                                  # ~4 minutes, no station needed
./aixun gui --sim                             # try the GUI with the simulated station
```

With a station connected:

```bash
./aixun online get T3BS 1.16                  # firmware into firmware/ (use YOUR station's product)
./aixun probe JC_M_T3BS_1.16.bin              # read-only check
./aixun gui                                   # the updater
```

---

## Commands

| Command | What it does | Touches the station? |
|---|---|---|
| `./aixun gui` | Graphical updater | Reads; writes only after you confirm |
| `./aixun gui --sim` | GUI against the built-in simulator | No |
| `./aixun probe FILE.bin` | Read-only probe + image check; report saved in `results/` | Reads only |
| `./aixun flash FILE.bin` | Command-line updater (asks for `yes`) | Writes |
| `./aixun online list / get / compare` | Firmware list, download, comparison with aixun-updates.github.io | No |
| `./aixun history [import]` | Flash history; import earlier logs | No |
| `./aixun test` | Test suite | No |
| `./aixun status` · `reinstall` · `rebuild-venv` | Workspace maintenance | No |
| `./aixun help` | All commands | |

The package also installs `t3x-probe`, `t3x-update`, `t3x-image`, `t3x-online`, `t3x-history`
and `t3x-gui` inside the workspace's venv (`./aixun run <command>`).

---

## Safety notes

- **Probe first.** It's read-only and tells you the station's real product line (the sticker may say T3B while the firmware is T3BS).
- **Keep a rollback image** of the version currently on the station: firmware can't be read back.
- **During a flash** (about 25 s): don't unplug, don't power off. Use a direct USB data cable, no hub.
- **If a flash fails**, leave the station on and connected, and use **Resume / retry** (GUI) or run the same command again. The station waits in its bootloader.
- On desktops running **ModemManager**, consider stopping it during a flash (the GUI tells you how).

---

## Folder structure

### This repository

```text
aixun-t3x-safe-flasher/
├── README.md, INSTALLATION.md, CONTRIBUTING.md, ROADMAP.md, CHANGELOG.md, LICENSE
├── pyproject.toml            package definition: dependencies, commands (t3x-probe, t3x-gui …)
├── src/t3x/                  the Python package
│   ├── core/                 engine without any user interface: image checks, protocol, serial link,
│   │                         flasher, read-only probe, logs, history, firmware online
│   ├── cli/                  command-line tools: t3x-probe, t3x-update, t3x-image, t3x-online, t3x-history
│   ├── gui/                  PySide6 graphical updater: t3x-gui
│   └── sim/                  simulated station for tests and demos: t3x-sim
├── tests/                    pytest suite (runs against the simulator; no station needed)
│   ├── reference/            the original, hardware-proven scripts, frozen: byte-for-byte reference
│   └── data/                 example flash log with the USB serial number anonymised
├── tools/
│   ├── aixun.sh              workspace manager behind ./aixun (optional)
│   └── check_publish.py      scan for files that must never be published
├── constraints/tested.txt    exact package versions of the tested environment
├── docs/                     development report, devlogs, workflow, guides, screenshots (img/)
├── .github/                  automatic tests on GitHub, issue and pull-request templates
└── t3x_probe.py, t3xupdate_safe.py   wrappers with the names of the earlier console scripts
```

### The workspace on your computer (made by `./aixun setup`)

The repository is cloned into a folder called `project`. Setup creates the rest next to it. None of it
is part of the repository:

```text
aixun/                        the workspace: any folder you choose
├── aixun                     shortcut to project/tools/aixun.sh
├── project/                  this repository (git clone)
├── venv/                     private Python environment
├── firmware/                 firmware images (.bin): downloaded by you, never committed
├── results/                  flash logs, probe reports, history.jsonl (contain the station's USB serial number)
├── config/                   GUI preferences (created the first time the GUI saves them)
└── deliveries/               zip snapshots of project/ applied with ./aixun apply (see below)
```

---

## Documentation

| Document | For |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | Setting up from scratch on any Linux distribution |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Developing: standard Python workflow, tests, the simulator, hardware testing |
| [ROADMAP.md](ROADMAP.md) | What is planned, **where help is wanted**, good first issues |
| [docs/MAINTAINERS.md](docs/MAINTAINERS.md) | Pushing changes and making releases |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Reference for the `./aixun` workspace: every command, snapshots, the simulator |
| [docs/SCRIPTS_GUIDE.md](docs/SCRIPTS_GUIDE.md) | Why not Windows, T3B vs T3BS, protocol and file format, the standalone scripts |
| [docs/DEVELOPMENT_REPORT.md](docs/DEVELOPMENT_REPORT.md) | Architecture, safety invariants, decisions, test matrix, hardware log, limitations |
| [docs/devlog/](docs/devlog/) | One log per development session (see below) |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

---

## Related projects

| Project | Relation |
|---|---|
| [c0d3z3r0/aixun_t3x_updater](https://github.com/c0d3z3r0/aixun_t3x_updater) | The original console updater this work is based on |
| [dzalf/aixun_t3x_safe_updater_and_probe](https://github.com/dzalf/aixun_t3x_safe_updater_and_probe) | The earlier console scripts (`t3x_probe.py`, `t3xupdate_safe.py`); still available, unchanged. This repository includes equivalent wrappers |

---

## How this project is developed

This project was developed in working sessions with an AI coding assistant (Claude, by Anthropic).
In each session the assistant made the changes in its own environment and handed them over as a **zip
snapshot of the project folder**. The maintainer applied the snapshot on a test branch with
`./aixun apply`, tested it on a Raspberry Pi 5 with a real station, and kept it (`./aixun accept`) or
discarded it (`./aixun rollback`). Each session is recorded in [docs/devlog/](docs/devlog/). Every
firmware write to a real station was decided and carried out by the maintainer.

**An AI assistant is not needed to work on this project.** It made development much faster, but the
code is ordinary Python, the tests are ordinary pytest, and contributions arrive as ordinary pull
requests ([CONTRIBUTING.md](CONTRIBUTING.md)). A snapshot zip isn't special either: it is the project
folder packed by git, and anyone can make one:

```bash
git -C project archive --format=zip --prefix=project/ -o my_change.zip HEAD
# packs every file git tracks in project/ into my_change.zip, inside a top folder called project/
```

---

## Credits and license

- **Michael Niewöhner ([@c0d3z3r0](https://github.com/c0d3z3r0))**: the original
  [`aixun_t3x_updater`](https://github.com/c0d3z3r0/aixun_t3x_updater) (kept unchanged in
  `tests/reference/`) and [`aixun_t3a_rev`](https://github.com/c0d3z3r0/aixun_t3a_rev). The protocol,
  file format and flash layout come from his work. Contributors to the original updater are in
  this repository's git history.
- [aixun-updates.github.io](https://aixun-updates.github.io/): unofficial firmware archive and changelogs.
- Probe, hardened updater, package, GUI and workspace: Dr. Daniel Melendrez,
  [Ivory Electronics](https://www.ivory-electronics.com).

Licensed under **GPL-2.0-or-later**, the licence of the original updater. See [LICENSE](LICENSE).
Firmware images are AiXun's and are not distributed here.

AiXun and JCID are trademarks of their respective owners.
